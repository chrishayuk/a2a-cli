#!/usr/bin/env python3
# a2a_cli/chat/commands/tasks.py
"""
Task-management slash-commands for the interactive A2A CLI.

Implemented commands
────────────────────
/send                → fire-and-forget task
/send_subscribe      → send + live stream     (alias: /sendsubscribe, /watch_text)
/get                 → fetch a task by id
/cancel              → cancel a running task
/resubscribe         → re-attach to a task’s stream (alias: /watch)
/artifacts           → browse / dump artifacts collected in this session

May 2025 highlights
───────────────────
* Every TaskSendParams now carries the session-id that the CLI generated at
  start-up so the server can thread a true conversation.
* Live streaming restores the **pretty green “Artifact:” panels**: each artifact
  appears immediately without erasing the status line.
* New `/artifacts` command:
    • `/artifacts`          – list all artifacts (with a Rich table)  
    • `/artifacts 3`        – pretty-print artifact #3  
    • `/artifacts 3 save`   – write artifact #3 to a file in the CWD
"""

from __future__ import annotations

import os
import pathlib
import uuid
from typing import Any, Dict, List, Optional

from rich import print                    # pylint: disable=redefined-builtin
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
    format_artifact_event,           # used for final summaries
    format_status_event,
)

# ════════════════════════════════════════════════════════════════════════════
# helper – remember every artifact so /artifacts can use them
# ════════════════════════════════════════════════════════════════════════════
def _cache_artifact(ctx: Dict[str, Any], task_id: str, art) -> None:          # noqa: ANN401
    ctx.setdefault("artifact_index", []).append(
        {
            "artifact": art,
            "task_id": task_id,
            "name": art.name or "<unnamed>",
            "mime": getattr(getattr(art, "parts", [None])[0], "mime_type", "text/plain"),
        }
    )


# ════════════════════════════════════════════════════════════════════════════
# helper – pretty-print ONE artifact (only text-parts are shown)
# ════════════════════════════════════════════════════════════════════════════
def _display_artifact(artifact: Any, console: Console | None = None) -> None:  # noqa: ANN401
    if console is None:
        console = Console()
    title = f"Artifact: {getattr(artifact, 'name', None) or '<unnamed>'}"
    for part in getattr(artifact, "parts", []):
        text = getattr(part, "text", None)
        if text is None and hasattr(part, "model_dump"):                      # custom part
            dumped = part.model_dump()
            if isinstance(dumped, dict):
                text = dumped.get("text")
        if text:
            console.print(Panel(text, title=title, border_style="green"))
            return
    console.print(Panel("[no displayable text]", title=title, border_style="green"))


def _display_artifacts(task: Any, console: Console | None = None) -> None:     # noqa: ANN401
    if console is None:
        console = Console()
    for art in getattr(task, "artifacts", []) or []:
        _display_artifact(art, console)


# ════════════════════════════════════════════════════════════════════════════
# /artifacts  ─ list, view or save artifacts
# ════════════════════════════════════════════════════════════════════════════
async def cmd_artifacts(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    store: List[Dict[str, Any]] = context.get("artifact_index", [])
    if not store:
        print("No artifacts collected in this session yet.")
        return True

    # no extra arg → render table
    if len(cmd_parts) == 1:
        table = Table(title=f"Artifacts ({len(store)})", title_style="cyan", box=None)
        table.add_column("#", justify="right")
        table.add_column("Task ID", overflow="fold")
        table.add_column("Name")
        table.add_column("MIME")
        for idx, meta in enumerate(store, start=1):
            table.add_row(str(idx), meta["task_id"][:8] + "…", meta["name"], meta["mime"])
        console = Console()
        console.print(table)
        return True

    # try to parse an index
    try:
        index = int(cmd_parts[1])
    except ValueError:
        print("[yellow]Usage: /artifacts [n] [save][/yellow]")
        return True

    if index < 1 or index > len(store):
        print(f"[red]Invalid index {index}. Use /artifacts to list.[/red]")
        return True

    meta = store[index - 1]
    artifact = meta["artifact"]

    if len(cmd_parts) == 3 and cmd_parts[2].lower() == "save":
        filename = _make_filename(meta, index)
        _save_artifact(artifact, filename)
        print(f"[green]Saved #{index} → {filename}[/green]")
    else:
        _display_artifact(artifact)

    return True


def _make_filename(meta: Dict[str, Any], idx: int) -> str:
    """Generate a friendly filename for the artifact."""
    name = meta["name"] or "artifact"
    name = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)[:32]
    ext  = _guess_extension(meta["mime"])
    return f"{idx:03d}_{name}{ext}"


def _guess_extension(mime: str) -> str:
    if mime.startswith("text/"):
        return ".txt"
    if mime in ("image/png", "image/x-png"):
        return ".png"
    if mime in ("image/jpeg", "image/jpg"):
        return ".jpg"
    if mime == "application/json":
        return ".json"
    return ".bin"


def _save_artifact(artifact: Any, filename: str) -> None:                      # noqa: ANN401
    path = pathlib.Path(filename).expanduser().resolve()
    data_written = False
    for part in getattr(artifact, "parts", []):
        if hasattr(part, "text"):
            path.write_text(part.text)
            data_written = True
            break
        if hasattr(part, "data"):
            path.write_bytes(part.data)  # type: ignore[arg-type]
            data_written = True
            break
    if not data_written:  # fallback
        path.write_text("<unserialisable artifact>")


# ════════════════════════════════════════════════════════════════════════════
# /send – plain send, no streaming
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
# /get – fetch existing task
# ════════════════════════════════════════════════════════════════════════════
async def cmd_get(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    client: A2AClient | None = context.get("client")
    if client is None:
        print("[red]Not connected – use /connect first.[/red]")
        return True

    task_id = cmd_parts[1] if len(cmd_parts) > 1 else context.get("last_task_id")
    if not task_id:
        print("[yellow]No task ID given & no previous task.[/yellow]")
        return True

    task = await client.get_task(TaskQueryParams(id=task_id))
    console = Console()
    display_task_info(task, console=console)

    if getattr(task, "status", None) and task.status.message and task.status.message.parts:
        texts = [p.text for p in task.status.message.parts if getattr(p, "text", None)]
        if texts:
            console.print(Panel("\n".join(texts), title="Task Message", border_style="blue"))

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
# /resubscribe – improved streaming (pretty artifacts)
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
                    live.refresh()                            # flush frame
                    _display_artifact(evt.artifact, console)  # immediate pretty panel
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
# /send_subscribe – send + live stream (pretty artifacts)
# ════════════════════════════════════════════════════════════════════════════
async def cmd_send_subscribe(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    if len(cmd_parts) < 2:
        print("[yellow]Usage: /send_subscribe <text>[/yellow]")
        return True

    # ensure clients --------------------------------------------------------
    base_url = context.get("base_url", "http://localhost:8000")
    rpc_url = f"{base_url.rstrip('/')}/rpc"
    events_url = f"{base_url.rstrip('/')}/events"

    http_client: A2AClient | None = context.get("client")
    if http_client is None:
        http_client = A2AClient.over_http(rpc_url)
        context["client"] = http_client

    sse_client: A2AClient | None = context.get("streaming_client")
    if sse_client is None:
        sse_client = A2AClient.over_sse(rpc_url, events_url)
        context["streaming_client"] = sse_client

    # params ----------------------------------------------------------------
    task_id = uuid.uuid4().hex
    params = TaskSendParams(
        id=task_id,
        session_id=context.get("session_id"),
        message=Message(role="user", parts=[TextPart(type="text", text=" ".join(cmd_parts[1:]))]),
    )
    context["last_task_id"] = task_id

    console = Console()
    print(f"[dim]Sending {task_id}…[/dim]")
    task = await http_client.send_task(params)
    display_task_info(task)

    print("[dim]Streaming updates … Ctrl-C to stop[/dim]")

    status_line = ""
    all_artifacts: List[Any] = []
    final_status = None

    try:
        with Live("", refresh_per_second=4, console=console) as live:
            async for evt in sse_client.send_subscribe(params):
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
        print("\n[yellow]Subscription interrupted.[/yellow]")
    except Exception as exc:  # noqa: BLE001
        print(f"[red]Error during streaming: {exc}[/red]")
        if context.get("debug_mode"):
            import traceback; traceback.print_exc()

    _finalise_stream(console, task_id, final_status, all_artifacts)
    return True


# ════════════════════════════════════════════════════════════════════════════
# helpers – common stream summariser
# ════════════════════════════════════════════════════════════════════════════
def _finalise_stream(
    console: Console,
    task_id: str,
    final_status,
    artifacts: List[Any],
) -> None:
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
register_command("/artifacts",       cmd_artifacts)

# legacy aliases
register_command("/watch",           cmd_resubscribe)
register_command("/sendsubscribe",   cmd_send_subscribe)
register_command("/watch_text",      cmd_send_subscribe)
