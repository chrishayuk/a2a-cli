#!/usr/bin/env python3
# a2a_cli/ui/ui_helpers.py
"""
UI helper functions for the A2A client CLI / chat UI.

Every helper here focuses on pretty-printing objects coming back from the
server (tasks, artifacts, status events) using the Rich library - no business
logic, only presentation.
"""
from __future__ import annotations

import json
import os
import platform
import sys
from typing import Any, Dict, List, Optional

from rich import print  # type: ignore  # pylint: disable=redefined-builtin
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from a2a_cli.ui.colors import *  # noqa: F403 - simple colour constants

# ────────────────────────────────────────────────────────────────────────────
#   Basic “chrome” helpers
# ────────────────────────────────────────────────────────────────────────────

def display_welcome_banner(context: Dict[str, Any], console: Console | None = None) -> None:
    """Show a friendly banner when the CLI starts."""
    if console is None:
        console = Console()

    base_url = context.get("base_url", "http://localhost:8000")

    header = "Welcome to A2A Client!\n\n"
    connection = f"[{TEXT_DEEMPHASIS}]Connected to: {base_url}[/{TEXT_DEEMPHASIS}]\n\n"
    hint = (
        f"Type [{TEXT_EMPHASIS}]'exit'[/{TEXT_EMPHASIS}] to quit or "
        f"[{TEXT_EMPHASIS}]'/help'[/{TEXT_EMPHASIS}] for commands."
    )

    console.print(
        Panel(
            header + connection + hint,
            title="Welcome to A2A Client",
            title_align="center",
            border_style=BORDER_PRIMARY,
            expand=True,
        )
    )


def display_markdown_panel(content: str, *, title: str | None = None, style: str = TEXT_INFO) -> None:
    """Render a block of Markdown inside a coloured panel."""
    Console().print(Panel(Markdown(content), title=title, style=style))


# ────────────────────────────────────────────────────────────────────────────
#   Task display helpers
# ────────────────────────────────────────────────────────────────────────────

def _status_colour(state: str) -> str:
    """Return the Rich colour name for a task state string."""
    return {
        "pending": TEXT_WARNING,
        "running": TEXT_INFO,
        "completed": TEXT_SUCCESS,
        "cancelled": TEXT_DEEMPHASIS,
        "failed": TEXT_ERROR,
    }.get(state.lower(), TEXT_NORMAL)


def display_task_info(task: Any, *, color: bool = True, console: Console | None = None) -> None:  # noqa: ANN401
    """Pretty-print the *entire* Task object, including artifacts (summarised)."""
    if console is None:
        console = Console()

    # Head-line details --------------------------------------------------
    state = task.status.state.value if getattr(task, "status", None) else "<unknown>"
    details: List[str] = [f"Task ID: {task.id}"]

    # Session id - only if present to avoid AttributeError on old servers
    session_id = getattr(task, "session_id", None)
    if session_id:
        details.append(f"Session: {session_id}")

    details.append(f"Status: [{_status_colour(state)}]{state}[/{_status_colour(state)}]")

    # Optional status message ------------------------------------------
    if (
        getattr(task, "status", None)
        and task.status.message
        and task.status.message.parts
        and task.status.message.parts[0].text
    ):
        details.append(f"Message: {task.status.message.parts[0].text}")

    # Artifacts (summary - not full content) ---------------------------
    if getattr(task, "artifacts", None):
        details.append("\nArtifacts:")
        for art in task.artifacts:
            details.append(
                f"  • [{ARTIFACT_COLOR}]{art.name or '<unnamed>'}[/{ARTIFACT_COLOR}]"
            )
            for part in art.parts:
                if getattr(part, "text", None):
                    snippet = part.text[:200] + ("…" if len(part.text) > 200 else "")
                    details.append(f"    {snippet}")
                elif getattr(part, "mime_type", None):
                    details.append(f"    [dim]MIME: {part.mime_type}[/dim]")

    console.print(Panel("\n".join(details), title="Task Details", border_style=BORDER_SECONDARY))


# ────────────────────────────────────────────────────────────────────────────
#   Event-stream formatting helpers
# ────────────────────────────────────────────────────────────────────────────

def format_status_event(event: Any) -> str:  # noqa: ANN401 - TaskStatusUpdateEvent
    """Return a single-line Rich string for *status* SSE events."""
    state = event.status.state.value
    message = ""
    if event.status.message and event.status.message.parts:
        message = f" — {event.status.message.parts[0].text}"
    return (
        f"[{STATUS_UPDATE_COLOR}]Status:[/{STATUS_UPDATE_COLOR}] "
        f"[{_status_colour(state)}]{state}{message}[/{_status_colour(state)}]"
    )


def format_artifact_event(event: Any) -> str:  # noqa: ANN401 - TaskArtifactUpdateEvent
    """Return a concise Rich string for *artifact* SSE events."""
    name = event.artifact.name or "<unnamed>"
    parts_preview: List[str] = []
    for part in event.artifact.parts:
        if getattr(part, "text", None):
            snippet = part.text[:200] + ("…" if len(part.text) > 200 else "")
            parts_preview.append(f"  {snippet}")
        elif getattr(part, "mime_type", None):
            parts_preview.append(f"  [dim]MIME: {part.mime_type}[/dim]")
        else:
            parts_preview.append(f"  [dim]{type(part).__name__} data[/dim]")
    return f"[{ARTIFACT_UPDATE_COLOR}]Artifact: {name}[/{ARTIFACT_UPDATE_COLOR}]\n" + "\n".join(parts_preview)


# ────────────────────────────────────────────────────────────────────────────
#   Low-level utilities
# ────────────────────────────────────────────────────────────────────────────

def clear_screen() -> None:
    """Clear the console in a cross-platform way."""
    os.system("cls" if platform.system() == "Windows" else "clear")


def restore_terminal() -> None:
    """Best-effort attempt to restore sane TTY settings after a crash."""
    if sys.platform != "win32":
        os.system("stty sane")


# ────────────────────────────────────────────────────────────────────────────
#   Artifact display (full content)
# ────────────────────────────────────────────────────────────────────────────
async def display_artifact(artifact: Any, console: Console | None = None) -> None:  # noqa: ANN401
    """Render a *single* artifact (potentially large) inside a scrolling panel."""
    if console is None:
        console = Console()

    name = artifact.name or "<unnamed>"
    body: List[str] = []
    for part in artifact.parts:
        if getattr(part, "text", None):
            body.append(part.text)
        elif getattr(part, "mime_type", None):
            body.append(f"[dim]MIME: {part.mime_type}[/dim]")
            try:
                body.append(json.dumps(part.model_dump(exclude_none=True), indent=2))
            except Exception:  # noqa: BLE001 - could be arbitrary object
                body.append(str(part))
        else:
            try:
                body.append(json.dumps(part.model_dump(exclude_none=True), indent=2))
            except Exception:
                body.append(str(part))

    console.print(Panel("\n\n".join(body), title=f"Artifact: {name}", border_style=ARTIFACT_COLOR))


def display_task_artifacts(task: Any, console: Console | None = None) -> None:  # noqa: ANN401
    """Iterate through *all* artifacts of *task* and print each in full."""
    if console is None:
        console = Console()

    for artifact in getattr(task, "artifacts", []) or []:
        # display_artifact is async, but we are in a sync context here,
        # so spin a quick event loop.
        import asyncio  # local import to avoid on import side-effects

        asyncio.run(display_artifact(artifact, console))