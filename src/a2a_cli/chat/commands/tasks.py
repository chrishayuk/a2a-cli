#!/usr/bin/env python3
# a2a_cli/chat/commands/tasks.py
"""
Task-management slash-commands for the interactive A2A CLI.

Implemented commands
────────────────────
/send                 – fire-and-forget task (text)
/send_subscribe       – send + live-stream reply               (aliases: /watch_text, /sendsubscribe)
/send_image           – send a local PNG/JPEG and live-stream  (NEW!)
/get                  – fetch a task by id
/cancel               – cancel a running task
/resubscribe          – re-attach to a task’s stream           (alias: /watch)
/artifacts            – browse / dump artifacts collected in this session

May 2025 highlights
───────────────────
* Every task now carries the CLI’s session-id so the backend can build real
  conversation memory.
* Live streaming restores the green “Artifact:” panels — each artifact appears
  immediately without erasing the status line.
* `/artifacts` command with list / pretty-view / save.
* **Multimodal:** image parts are rendered inline and you can send images via
  `/send_image <path> [caption …]`.
"""
from __future__ import annotations

import base64
import mimetypes
import os
import pathlib
import tempfile
import uuid
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict

from rich import print                             # pylint: disable=redefined-builtin
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from a2a_cli.chat.commands import register_command
from a2a_cli.a2a_client import A2AClient
from a2a_json_rpc.spec import (
    Message,
    TaskArtifactUpdateEvent,
    TaskIdParams,
    TaskQueryParams,
    TaskSendParams,
    TaskStatusUpdateEvent,
    TextPart,
)
from a2a_cli.ui.ui_helpers import (
    display_task_info,
    format_artifact_event,
    format_status_event,
)
from a2a_cli.ui.ansi_preview import render_img   # <— new import

try:
    # Newer a2a_json_rpc already exports BinaryPart; just forward-import it.
    from a2a_json_rpc.spec import BinaryPart          # noqa: F401

except ImportError:                                   # pre-0.11 → make our own
    @dataclass
    class BinaryPart:                                 # type: ignore[override]
        """
        Minimal stand-in for a2a_json_rpc.spec.BinaryPart.

        Attributes
        ----------
        type        fixed value ``"binary"`` (kept for wire-compat).
        mime_type   full MIME type (``image/png``, ``audio/wav`` …).
        data        raw payload bytes.
        """

        mime_type: str
        data: bytes
        type: str = "binary"                          # wire-format discriminator

        # --- helpers so existing code that expects a Pydantic model still works --

        def model_dump(self, *_, **__) -> Dict[str, Any]:         # Pydantic 1.x API
            return asdict(self)

        def dict(self, *_, **__) -> Dict[str, Any]:               # many libraries use this
            return asdict(self)

        # make the object indexable like a Mapping if someone does .get("mime_type")
        def __getitem__(self, item):                              # noqa: Dunder
            return getattr(self, item)

        # readable repr for logging / debugging
        def __repr__(self) -> str:                                # noqa: Dunder
            size = len(self.data)
            return f"BinaryPart(mime_type={self.mime_type!r}, bytes={size})"
        
# ------------------------------------------------------------------------

# ════════════════════════════════════════════════════════════════════════════
# small helpers
# ════════════════════════════════════════════════════════════════════════════
def _cache_artifact(ctx: Dict[str, Any], task_id: str, art) -> None:  # noqa: ANN401
    """Remember *art* in context so `/artifacts` can find it."""
    ctx.setdefault("artifact_index", []).append(
        {
            "artifact": art,
            "task_id": task_id,
            "name": art.name or "<unnamed>",
            "mime": getattr(getattr(art, "parts", [None])[0], "mime_type", "text/plain"),
        }
    )


def _make_image_part(path: str) -> BinaryPart:
    """
    Read *path* and return a BinaryPart whose `data` field is **base-64 text**
    so the JSON encoder can transmit it safely.
    """
    fp = pathlib.Path(path).expanduser().resolve()
    if not fp.is_file():
        raise FileNotFoundError(fp)

    raw  = fp.read_bytes()
    b64  = base64.b64encode(raw).decode("ascii")        # ← utf-8 friendly
    mime, _ = mimetypes.guess_type(fp.name)
    if not mime or not mime.startswith("image/"):
        raise ValueError("Only PNG/JPEG images are supported")

    return BinaryPart(mime_type=mime, data=b64)         # <── b64 text here


# ═══════════════════════════════════════════════════════════════════════════
# artifact display helpers
# ═══════════════════════════════════════════════════════════════════════════
def _display_artifact(artifact: Any, console: Console | None = None) -> None:
    """Pretty-print one artifact (inline ANSI image or text)."""
    if console is None:
        console = Console()

    title = f"Artifact: {getattr(artifact, 'name', None) or '<unnamed>'}"

    for part in getattr(artifact, "parts", []) or []:

        # ── image preview ────────────────────────────────────────────────
        if getattr(part, "mime_type", "").startswith("image/"):
            raw: bytes | str = getattr(part, "data", b"")
            if isinstance(raw, str):                     # base-64 on the wire
                try:
                    raw = base64.b64decode(raw)
                except Exception:                        # pragma: no cover
                    raw = b""
            img_txt = render_img(raw, part.mime_type, max_width=40)
            if img_txt:
                console.print(
                    Panel(Text.from_ansi(img_txt), title=title,
                          border_style="green", padding=0)
                )
                return

        # ── plain-text preview ───────────────────────────────────────────
        text = getattr(part, "text", None)
        if text is None and hasattr(part, "model_dump"):
            dumped = part.model_dump()
            if isinstance(dumped, dict):
                text = dumped.get("text")
        if text:
            console.print(Panel(text, title=title, border_style="green"))
            return

    console.print(Panel("[no displayable preview]", title=title,
                        border_style="green"))

def _display_artifacts(task: Any, console: Console | None = None) -> None:  # noqa: ANN401
    if console is None:
        console = Console()
    for art in getattr(task, "artifacts", []) or []:
        _display_artifact(art, console)


# ════════════════════════════════════════════════════════════════════════════
# /artifacts  – list / view / save
# ════════════════════════════════════════════════════════════════════════════
async def cmd_artifacts(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    store: List[Dict[str, Any]] = context.get("artifact_index", [])
    if not store:
        print("No artifacts collected in this session yet.")
        return True

    # list table -------------------------------------------------------------
    if len(cmd_parts) == 1:
        table = Table(title=f"Artifacts ({len(store)})", title_style="bold cyan")
        table.add_column("#", justify="right", style="dim")
        table.add_column("Task-ID", overflow="fold")
        table.add_column("Name")
        table.add_column("MIME")
        for i, meta in enumerate(store, start=1):
            table.add_row(str(i), meta["task_id"][:8] + "…", meta["name"], meta["mime"])
        Console().print(table)
        return True

    # parse index ------------------------------------------------------------
    try:
        idx = int(cmd_parts[1])
    except ValueError:
        print("[yellow]Usage: /artifacts [n] [save][/yellow]")
        return True

    if idx < 1 or idx > len(store):
        print(f"[red]Invalid index {idx}. Use /artifacts to list.[/red]")
        return True

    meta = store[idx - 1]
    artifact = meta["artifact"]

    # save to disk -----------------------------------------------------------
    if len(cmd_parts) == 3 and cmd_parts[2].lower() == "save":
        filename = _make_filename(meta, idx)
        _save_artifact(artifact, filename)
        print(f"[green]Saved #{idx} → {filename}[/green]")
        return True

    # pretty-print the artifact ---------------------------------------------
    _display_artifact(artifact)
    return True


def _make_filename(meta: Dict[str, Any], idx: int) -> str:
    base = "".join(c if c.isalnum() or c in "._-" else "_" for c in meta["name"]) or "artifact"
    base = base[:32]
    ext = _guess_ext(meta["mime"])
    return f"{idx:03d}_{base}{ext}"


def _guess_ext(mime: str) -> str:
    if mime.startswith("text/"):
        return ".txt"
    if mime in ("image/png", "image/x-png"):
        return ".png"
    if mime in ("image/jpeg", "image/jpg"):
        return ".jpg"
    if mime == "application/json":
        return ".json"
    return ".bin"


def _save_artifact(artifact: Any, filename: str) -> None:  # noqa: ANN401
    path = pathlib.Path(filename).expanduser().resolve()
    for part in getattr(artifact, "parts", []):
        if hasattr(part, "text"):
            path.write_text(part.text)
            return
        if hasattr(part, "data"):
            path.write_bytes(part.data)  # type: ignore[arg-type]
            return
    path.write_text("<unserialisable artifact>")


# ════════════════════════════════════════════════════════════════════════════
# /send (text, no streaming)
# ════════════════════════════════════════════════════════════════════════════
async def cmd_send(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    if len(cmd_parts) < 2:
        print("[yellow]Usage: /send <text>[/yellow]")
        return True

    client: A2AClient | None = context.get("client")
    if client is None:
        print("[red]Not connected – use /connect first.[/red]")
        return True

    text = " ".join(cmd_parts[1:])
    task_id = uuid.uuid4().hex
    params = TaskSendParams(
        id=task_id,
        session_id=context.get("session_id"),
        message=Message(role="user", parts=[TextPart(type="text", text=text)]),
    )

    print(f"[dim]Sending task {task_id}…[/dim]")
    task = await client.send_task(params)
    context["last_task_id"] = task_id
    display_task_info(task)

    if getattr(task, "artifacts", None):
        print(f"\n[bold]Artifacts ({len(task.artifacts)}):[/bold]")
        _display_artifacts(task)
        for art in task.artifacts:
            _cache_artifact(context, task_id, art)
    return True


# ════════════════════════════════════════════════════════════════════════════
# /get
# ════════════════════════════════════════════════════════════════════════════
async def cmd_get(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    client: A2AClient | None = context.get("client")
    if client is None:
        print("[red]Not connected – use /connect first.[/red]")
        return True

    task_id = cmd_parts[1] if len(cmd_parts) > 1 else context.get("last_task_id")
    if not task_id:
        print("[yellow]No task ID given.[/yellow]")
        return True

    task = await client.get_task(TaskQueryParams(id=task_id))
    console = Console()
    display_task_info(task, console=console)

    if task.status and task.status.message and task.status.message.parts:
        txts = [p.text for p in task.status.message.parts if getattr(p, "text", None)]
        if txts:
            console.print(Panel("\n".join(txts), title="Task Message", border_style="blue"))

    if getattr(task, "artifacts", None):
        print(f"\n[bold]Artifacts ({len(task.artifacts)}):[/bold]")
        _display_artifacts(task, console)
        for art in task.artifacts:
            _cache_artifact(context, task_id, art)
    return True


# ════════════════════════════════════════════════════════════════════════════
# /cancel
# ════════════════════════════════════════════════════════════════════════════
async def cmd_cancel(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    client: A2AClient | None = context.get("client")
    if client is None:
        print("[red]Not connected – use /connect first.[/red]")
        return True

    task_id = cmd_parts[1] if len(cmd_parts) > 1 else context.get("last_task_id")
    if not task_id:
        print("[yellow]No task ID provided.[/yellow]")
        return True

    await client.cancel_task(TaskIdParams(id=task_id))
    print(f"[green]Cancelled {task_id}[/green]")
    return True


# ════════════════════════════════════════════════════════════════════════════
# /resubscribe – streaming with pretty artifacts
# ════════════════════════════════════════════════════════════════════════════
async def cmd_resubscribe(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    client: A2AClient | None = context.get("streaming_client") or context.get("client")
    if client is None:
        print("[red]Not connected – use /connect first.[/red]")
        return True

    task_id = cmd_parts[1] if len(cmd_parts) > 1 else context.get("last_task_id")
    if not task_id:
        print("[yellow]No task ID given.[/yellow]")
        return True

    console = Console()
    print(f"[dim]Resubscribing to {task_id} … Ctrl-C to stop[/dim]")

    status_line = ""
    all_artifacts: List[Any] = []
    final_status = None

    try:
        with Live("", refresh_per_second=4, console=console) as live:
            async for evt in client.resubscribe(TaskQueryParams(id=task_id)):
                if isinstance(evt, TaskStatusUpdateEvent):
                    status_line = format_status_event(evt)
                    live.update(Text.from_markup(status_line))
                    if evt.final:
                        final_status = evt.status
                        break

                elif isinstance(evt, TaskArtifactUpdateEvent):
                    live.refresh()
                    _display_artifact(evt.artifact, console)
                    live.update(Text.from_markup(status_line))
                    all_artifacts.append(evt.artifact)
                    _cache_artifact(context, task_id, evt.artifact)

    except KeyboardInterrupt:
        print("\n[yellow]Watch interrupted.[/yellow]")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[red]Error watching task: {exc}[/red]")
        if context.get("debug_mode"):
            import traceback; traceback.print_exc()
        return True

    _finalise_stream(console, task_id, final_status, all_artifacts)
    return True


# ════════════════════════════════════════════════════════════════════════════
# /send_subscribe (text)  – streaming with pretty artifacts
# ════════════════════════════════════════════════════════════════════════════
async def cmd_send_subscribe(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    if len(cmd_parts) < 2:
        print("[yellow]Usage: /send_subscribe <text>[/yellow]")
        return True
    text = " ".join(cmd_parts[1:])
    return await _send_and_stream(
        context,
        message_parts=[TextPart(type="text", text=text)],
    )


# ────────────────────────────────────────────────────────────────────────────
# /send_image  –  send a local image (+ optional caption) and stream reply
# ────────────────────────────────────────────────────────────────────────────
async def cmd_send_image(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    """
    /send_image <path.[png|jpg]>  [optional caption ...]

    • Reads the file, wraps it in a BinaryPart (base-64 payload when we’re on
      the compatibility shim).
    • Guarantees there’s at least ONE TextPart – the user caption or the
      placeholder “<image>” – so every back-end handler that requires text
      will be happy.
    • Immediately streams the response just like /send_subscribe.
    """
    if len(cmd_parts) < 2:
        print("[yellow]Usage: /send_image <path> [caption][/yellow]")
        return True

    img_path = pathlib.Path(cmd_parts[1]).expanduser()
    if not img_path.exists():
        print(f"[red]File not found: {img_path}[/red]")
        return True

    # ------------------------------------------------------------------ #
    # Build message parts
    # ------------------------------------------------------------------ #
    try:
        img_part = _make_image_part(str(img_path))       # BinaryPart (b64 payload on shim)
    except Exception as exc:                             # noqa: BLE001
        print(f"[red]Cannot read image: {exc}[/red]")
        return True

    caption = " ".join(cmd_parts[2:]) if len(cmd_parts) > 2 else "<image>"
    message_parts: List[Any] = [
        img_part,
        TextPart(type="text", text=caption),             # <-- guarantees a text part
    ]

    # ------------------------------------------------------------------ #
    # Re-use the generic send-and-stream helper
    # ------------------------------------------------------------------ #
    return await _send_and_stream(context, message_parts=message_parts)

async def _send_and_stream(context: Dict[str, Any], *, message_parts: List[Any]) -> bool:
    base_url = context.get("base_url", "http://localhost:8000")
    rpc_url, events_url = (f"{base_url.rstrip('/')}/{s}" for s in ("rpc", "events"))

    http_client: A2AClient | None = context.get("client")
    if http_client is None:
        http_client = A2AClient.over_http(rpc_url)
        context["client"] = http_client

    sse_client: A2AClient | None = context.get("streaming_client")
    if sse_client is None:
        sse_client = A2AClient.over_sse(rpc_url, events_url)
        context["streaming_client"] = sse_client

    # Client-generated task ID
    client_task_id = uuid.uuid4().hex
    params = TaskSendParams(
        id=client_task_id,
        session_id=context.get("session_id"),
        message=Message(role="user", parts=message_parts),
    )
    
    console = Console()
    print(f"[dim]Sending {client_task_id}…[/dim]")
    
    # Send task and get server response
    task = await http_client.send_task(params)
    
    # Get the server-assigned task ID 
    server_task_id = getattr(task, "id", client_task_id)
    
    # Store the server ID for future reference
    context["last_task_id"] = server_task_id
    
    display_task_info(task)
    print("[dim]Streaming updates … Ctrl-C to stop[/dim]")

    status_line = ""
    all_artifacts: List[Any] = []
    final_status = None
    
    # Track response artifacts
    artifact_contents = {}  # key: artifact_name, value: content
    seen_artifacts = set()  # To track which artifacts we've seen

    try:
        from rich.console import Group
        
        with Live("", refresh_per_second=10, console=console) as live:
            async for evt in sse_client.send_subscribe(params):
                if isinstance(evt, TaskStatusUpdateEvent):
                    status_line = format_status_event(evt)
                    
                    # Create display with status line and all current artifact panels
                    display_parts = [Text.from_markup(status_line)]
                    
                    # Add panels for all response artifacts we're tracking
                    for name, content in artifact_contents.items():
                        display_parts.append(
                            Panel(
                                content,
                                title=f"Artifact: {name}",
                                border_style="green"
                            )
                        )
                    
                    # Update the display
                    live.update(Group(*display_parts))
                    
                    if evt.final:
                        final_status = evt.status
                        break

                elif isinstance(evt, TaskArtifactUpdateEvent):
                    artifact = evt.artifact
                    
                    # Only process if it has a name and parts
                    if hasattr(artifact, "name") and artifact.name and hasattr(artifact, "parts") and artifact.parts:
                        # Check if it's a response artifact or something we want to show inline
                        is_response_artifact = "_response" in artifact.name
                        
                        # Extract content
                        content = _extract_content(artifact)
                        
                        if is_response_artifact:
                            # Update our tracking dictionary for response artifacts
                            artifact_contents[artifact.name] = content
                            
                            # Create an updated display with all current artifacts
                            display_parts = [Text.from_markup(status_line)]
                            for name, content in artifact_contents.items():
                                display_parts.append(
                                    Panel(
                                        content,
                                        title=f"Artifact: {name}",
                                        border_style="green"
                                    )
                                )
                            
                            # Update the live display
                            live.update(Group(*display_parts))
                        else:
                            # For non-response artifacts (images, data, etc.)
                            # Only display them once
                            if artifact.name not in seen_artifacts:
                                seen_artifacts.add(artifact.name)
                                
                                # Temporarily stop Live display to show the artifact
                                live.stop()
                                _display_artifact(artifact, console)
                                live.start()
                                
                                # Restore the combined view afterward
                                display_parts = [Text.from_markup(status_line)]
                                for name, content in artifact_contents.items():
                                    display_parts.append(
                                        Panel(
                                            content,
                                            title=f"Artifact: {name}",
                                            border_style="green"
                                        )
                                    )
                                
                                if display_parts:
                                    live.update(Group(*display_parts))
                                else:
                                    live.update(Text.from_markup(status_line))
                    
                    # Track all artifacts for final display and caching
                    all_artifacts.append(artifact)
                    _cache_artifact(context, server_task_id, artifact)  # Use server ID for caching

    except KeyboardInterrupt:
        print("\n[yellow]Subscription interrupted.[/yellow]")
    except Exception as exc:  # noqa: BLE001
        print(f"[red]Error during streaming: {exc}[/red]")
        if context.get("debug_mode"):
            import traceback; traceback.print_exc()

    # Format task completion message in the same style as status updates
    # Use server_task_id for consistency with what's shown in display_task_info
    completion_message = f"[cyan]Status:[/cyan] [green]Task {server_task_id} completed[/green]"
    print(f"\n{completion_message}")
    return True

# Helper function to extract text content from an artifact
def _extract_content(artifact) -> str:
    """Extract a text representation of the artifact's content for comparison."""
    if not hasattr(artifact, "parts") or not artifact.parts:
        return ""
    
    part = artifact.parts[0]
    if hasattr(part, "text") and part.text:
        return part.text
    
    # For non-text parts
    if hasattr(part, "model_dump"):
        dumped = part.model_dump()
        if isinstance(dumped, dict):
            for key in ("text", "value", "content", "data"):
                if key in dumped and isinstance(dumped[key], str):
                    return dumped[key]
    
    return str(part)  # Fallback

# ════════════════════════════════════════════════════════════════════════════
# stream-summary helper
# ════════════════════════════════════════════════════════════════════════════
def _finalise_stream(console: Console, task_id: str, final_status, artifacts) -> None:  # noqa: ANN001
    if final_status:
        print(f"[green]Task {task_id} completed.[/green]")
        if final_status.message and final_status.message.parts:
            for p in final_status.message.parts:
                if getattr(p, "text", None):
                    console.print(Panel(p.text, title="Response", border_style="blue"))
    if artifacts:
        print(f"\n[bold]Artifacts ({len(artifacts)}):[/bold]")
        for art in artifacts:
            _display_artifact(art, console)


# ════════════════════════════════════════════════════════════════════════════
# command registration
# ════════════════════════════════════════════════════════════════════════════
register_command("/send",            cmd_send)
register_command("/get",             cmd_get)
register_command("/cancel",          cmd_cancel)
register_command("/resubscribe",     cmd_resubscribe)
register_command("/send_subscribe",  cmd_send_subscribe)
register_command("/send_image",      cmd_send_image)
register_command("/artifacts",       cmd_artifacts)

# legacy aliases
register_command("/watch",           cmd_resubscribe)
register_command("/sendsubscribe",   cmd_send_subscribe)
register_command("/watch_text",      cmd_send_subscribe)
