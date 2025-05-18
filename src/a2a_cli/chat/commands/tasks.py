#!/usr/bin/env python3
# a2a_cli/chat/commands/tasks.py
"""
Task-management commands for the A2A client CLI.

Supported slash-commands:
    /send               → tasks/send
    /send_subscribe     → tasks/sendSubscribe
    /get                → tasks/get
    /cancel             → tasks/cancel
    /resubscribe        → tasks/resubscribe
    (aliases: /watch, /sendsubscribe, /watch_text)

May 2025 update
───────────────
* Every TaskSendParams now sets `session_id=context.get("session_id")`
  so the server threads all tasks into a single conversation.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List, Optional

from rich import print  # pylint: disable=redefined-builtin
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
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

# ────────────────────────────────────────────────────────────────────────────
# Inline helpers (kept local to avoid circular imports)
# ────────────────────────────────────────────────────────────────────────────
def _display_artifact(artifact: Any, console: Console | None = None) -> None:  # noqa: ANN401
    if console is None:
        console = Console()
    name = getattr(artifact, "name", None) or "<unnamed>"
    for part in getattr(artifact, "parts", []):
        text = getattr(part, "text", None)
        if (
            text is None
            and hasattr(part, "model_dump")
            and isinstance(part.model_dump(), dict)
        ):
            text = part.model_dump().get("text")
        if text:
            console.print(Panel(text, title=f"Artifact: {name}", border_style="green"))
            return
    console.print(
        Panel("[no displayable text]", title=f"Artifact: {name}", border_style="green")
    )


def _display_artifacts(task: Any, console: Console | None = None) -> None:  # noqa: ANN401
    if console is None:
        console = Console()
    for art in getattr(task, "artifacts", []) or []:
        _display_artifact(art, console)


# ────────────────────────────────────────────────────────────────────────────
# /send
# ────────────────────────────────────────────────────────────────────────────
async def cmd_send(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    if len(cmd_parts) < 2:
        print("[yellow]Usage: /send <text>[/yellow]")
        return True

    client: A2AClient | None = context.get("client")
    if client is None:
        print("[red]Not connected - use /connect first.[/red]")
        return True

    text = " ".join(cmd_parts[1:])
    task_id = str(uuid.uuid4())

    params = TaskSendParams(
        id=task_id,
        session_id=context.get("session_id"),  # <-- key line
        message=Message(role="user", parts=[TextPart(type="text", text=text)]),
    )

    try:
        print(f"[dim]Sending task with ID: {task_id}[/dim]")
        task = await client.send_task(params)
        context["last_task_id"] = task_id
        display_task_info(task)
        if getattr(task, "artifacts", None):
            print(f"\n[bold]Artifacts ({len(task.artifacts)}):[/bold]")
            _display_artifacts(task)
    except Exception as exc:  # noqa: BLE001
        print(f"[red]Error sending task: {exc}[/red]")
        if context.get("debug_mode"):
            import traceback; traceback.print_exc()
    return True


# ────────────────────────────────────────────────────────────────────────────
# /get
# ────────────────────────────────────────────────────────────────────────────
async def cmd_get(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    client: A2AClient | None = context.get("client")
    if client is None:
        print("[red]Not connected - use /connect first.[/red]")
        return True

    task_id = cmd_parts[1] if len(cmd_parts) > 1 else context.get("last_task_id")
    if not task_id:
        print("[yellow]No task ID provided and no previous task found.[/yellow]")
        return True

    try:
        task = await client.get_task(TaskQueryParams(id=task_id))
        console = Console()
        display_task_info(task, console=console)

        if (
            getattr(task, "status", None)
            and task.status.message
            and task.status.message.parts
        ):
            texts = [p.text for p in task.status.message.parts if getattr(p, "text", None)]
            if texts:
                console.print(
                    Panel("\n".join(texts), title="Task Message", border_style="blue")
                )

        if getattr(task, "artifacts", None):
            print(f"\n[bold]Artifacts ({len(task.artifacts)}):[/bold]")
            _display_artifacts(task, console)
    except Exception as exc:  # noqa: BLE001
        print(f"[red]Error getting task: {exc}[/red]")
        if context.get("debug_mode"):
            import traceback; traceback.print_exc()
    return True


# ────────────────────────────────────────────────────────────────────────────
# /cancel
# ────────────────────────────────────────────────────────────────────────────
async def cmd_cancel(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    client: A2AClient | None = context.get("client")
    if client is None:
        print("[red]Not connected - use /connect first.[/red]")
        return True

    task_id = cmd_parts[1] if len(cmd_parts) > 1 else context.get("last_task_id")
    if not task_id:
        print("[yellow]No task ID provided and no previous task found.[/yellow]")
        return True

    try:
        await client.cancel_task(TaskIdParams(id=task_id))
        print(f"[green]Successfully cancelled task {task_id}[/green]")
        await cmd_get(["/get", task_id], context)
    except Exception as exc:  # noqa: BLE001
        print(f"[red]Error cancelling task: {exc}[/red]")
        if context.get("debug_mode"):
            import traceback; traceback.print_exc()
    return True


# ────────────────────────────────────────────────────────────────────────────
# /resubscribe
# ────────────────────────────────────────────────────────────────────────────
async def cmd_resubscribe(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    client: A2AClient | None = context.get("streaming_client") or context.get("client")
    if client is None:
        print("[red]Not connected - use /connect first.[/red]")
        return True

    task_id = cmd_parts[1] if len(cmd_parts) > 1 else context.get("last_task_id")
    if not task_id:
        print("[yellow]No task ID provided and no previous task found.[/yellow]")
        return True

    console = Console()
    print(f"[dim]Resubscribing to task {task_id}. Press Ctrl+C to stop…[/dim]")

    all_artifacts: List[Any] = []
    final_status = None
    try:
        with Live("", refresh_per_second=4, console=console) as live:
            async for evt in client.resubscribe(TaskQueryParams(id=task_id)):
                if isinstance(evt, TaskStatusUpdateEvent):
                    live.update(Text.from_markup(format_status_event(evt)))
                    if evt.final:
                        final_status = evt.status
                        break
                elif isinstance(evt, TaskArtifactUpdateEvent):
                    live.update(Text.from_markup(format_artifact_event(evt)))
                    all_artifacts.append(evt.artifact)
                else:
                    live.update(Text(f"Unknown event: {type(evt).__name__}"))
    except KeyboardInterrupt:
        print("\n[yellow]Watch interrupted.[/yellow]")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[red]Error watching task: {exc}[/red]")
        if context.get("debug_mode"):
            import traceback; traceback.print_exc()
        return True

    if final_status:
        print(f"[green]Task {task_id} completed.[/green]")
        if final_status.message and final_status.message.parts:
            for part in final_status.message.parts:
                if getattr(part, "text", None):
                    console.print(Panel(part.text, title="Response", border_style="blue"))

    if all_artifacts:
        print(f"\n[bold]Artifacts ({len(all_artifacts)}):[/bold]")
        for art in all_artifacts:
            _display_artifact(art, console)
    return True


# ────────────────────────────────────────────────────────────────────────────
# /send_subscribe
# ────────────────────────────────────────────────────────────────────────────
async def cmd_send_subscribe(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    if len(cmd_parts) < 2:
        print("[yellow]Usage: /send_subscribe <text>[/yellow]")
        return True

    text = " ".join(cmd_parts[1:])

    # HTTP client
    http_client: A2AClient | None = context.get("client")
    base_url = context.get("base_url", "http://localhost:8000")
    rpc_url = f"{base_url.rstrip('/')}/rpc"
    if http_client is None:
        http_client = A2AClient.over_http(rpc_url)
        context["client"] = http_client

    # Streaming client
    sse_client: A2AClient | None = context.get("streaming_client")
    events_url = f"{base_url.rstrip('/')}/events"
    if sse_client is None:
        try:
            print(f"[dim]Initializing SSE client for {events_url}…[/dim]")
            sse_client = A2AClient.over_sse(rpc_url, events_url)
            context["streaming_client"] = sse_client
            print("[green]SSE client initialized[/green]")
        except Exception as exc:  # noqa: BLE001
            print(f"[yellow]Streaming not available: {exc}[/yellow]")
            sse_client = None

    # Send params
    task_id = str(uuid.uuid4())
    params = TaskSendParams(
        id=task_id,
        session_id=context.get("session_id"),  # <-- key line
        message=Message(role="user", parts=[TextPart(type="text", text=text)]),
    )
    context["last_task_id"] = task_id

    console = Console()
    print(f"[dim]Sending task with ID: {task_id}[/dim]")

    # Initial request
    try:
        task = await http_client.send_task(params)
        display_task_info(task)
    except Exception as exc:  # noqa: BLE001
        print(f"[red]Error sending task: {exc}[/red]")
        if context.get("debug_mode"):
            import traceback; traceback.print_exc()
        return True

    # Stream
    if sse_client:
        print("[dim]Subscribing to updates. Press Ctrl+C to stop…[/dim]")
        all_artifacts: List[Any] = []
        final_status = None
        try:
            with Live("", refresh_per_second=4, console=console) as live:
                async for evt in sse_client.send_subscribe(params):
                    if isinstance(evt, TaskStatusUpdateEvent):
                        live.update(Text.from_markup(format_status_event(evt)))
                        if evt.final:
                            final_status = evt.status
                            break
                    elif isinstance(evt, TaskArtifactUpdateEvent):
                        live.update(Text.from_markup(format_artifact_event(evt)))
                        all_artifacts.append(evt.artifact)
                    else:
                        live.update(Text(f"Unknown event: {type(evt).__name__}"))
        except KeyboardInterrupt:
            print("\n[yellow]Subscription interrupted.[/yellow]")
        except Exception as exc:  # noqa: BLE001
            print(f"\n[red]Error during streaming: {exc}[/red]")
            if context.get("debug_mode"):
                import traceback; traceback.print_exc()

        # final output
        if final_status:
            print(f"[green]Task {task_id} completed.[/green]")
            if final_status.message and final_status.message.parts:
                for part in final_status.message.parts:
                    if getattr(part, "text", None):
                        console.print(
                            Panel(part.text, title="Response", border_style="blue")
                        )

        if all_artifacts:
            print(f"\n[bold]Artifacts ({len(all_artifacts)}):[/bold]")
            for art in all_artifacts:
                _display_artifact(art, console)

    return True


# ────────────────────────────────────────────────────────────────────────────
# Command registration
# ────────────────────────────────────────────────────────────────────────────
register_command("/send", cmd_send)
register_command("/get", cmd_get)
register_command("/cancel", cmd_cancel)
register_command("/resubscribe", cmd_resubscribe)
register_command("/send_subscribe", cmd_send_subscribe)

# legacy aliases
register_command("/watch", cmd_resubscribe)
register_command("/sendsubscribe", cmd_send_subscribe)
register_command("/watch_text", cmd_send_subscribe)
