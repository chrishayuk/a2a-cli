#!/usr/bin/env python3
# a2a_cli/cli.py
"""
A2A Client CLI

Provides a rich, interactive command-line interface for the Agent-to-Agent
(A2A) protocol.  Supports sending, watching and chatting with tasks over a
running A2A server.

May 2025
────────
* Session persistence – a single random ``session_id`` is generated when the
  CLI starts and automatically attached to every task you send so the server
  can build real conversation memory.
* Cleaner logging flags (``--debug``, ``--quiet``, ``--log-level``).
* Graceful terminal restore on Ctrl-C / signals.
* **May 18, 2025:** streaming views now show every artifact the moment it
  arrives (no more “last one wins”).
"""
from __future__ import annotations

import atexit
import asyncio
import json
import logging
import os
import signal
import sys
import uuid
from typing import Optional

import typer
from rich.console import Console
from rich import print

from a2a_json_rpc.json_rpc_errors import JSONRPCError
from a2a_json_rpc.spec import (
    Message,
    TaskArtifactUpdateEvent,
    TaskIdParams,
    TaskQueryParams,
    TaskSendParams,
    TaskStatusUpdateEvent,
    TextPart,
)

from a2a_cli.a2a_client import A2AClient
from a2a_cli.chat.chat_handler import handle_chat_mode
from a2a_cli.ui.ui_helpers import (
    display_task_info,
    format_artifact_event,
    format_status_event,
    restore_terminal,
)

# ────────────────────────────────────────────────────────────────────────────
# Constants & helpers
# ────────────────────────────────────────────────────────────────────────────
DEFAULT_HOST = "http://localhost:8000"
RPC_SUFFIX = "/rpc"
EVENTS_SUFFIX = "/events"

# One session id for the entire CLI run – lets the server remember context
CLI_SESSION_ID: str = uuid.uuid4().hex

# ────────────────────────────────────────────────────────────────────────────
# Logging helpers
# ────────────────────────────────────────────────────────────────────────────
def _setup_logging(debug: bool, quiet: bool, level_name: str) -> None:
    level = (
        logging.DEBUG
        if debug
        else (logging.ERROR if quiet else getattr(logging, level_name.upper(), logging.INFO))
    )
    root = logging.getLogger()
    root.setLevel(logging.ERROR)  # squelch third-party noise

    cli = logging.getLogger("a2a-cli")
    cli.setLevel(level)

    fmt = "%(asctime)s - %(levelname)s - %(message)s" if debug else "%(message)s"
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter(fmt))

    for lg in (root, cli, logging.getLogger("httpx"), logging.getLogger("a2a-client.sse")):
        if lg:
            lg.handlers.clear()
            lg.addHandler(h)
            lg.propagate = False


def _resolve_base(prefix: Optional[str]) -> str:
    if prefix and prefix.startswith(("http://", "https://")):
        return prefix.rstrip("/")
    if prefix:
        return f"{DEFAULT_HOST.rstrip('/')}/{prefix.strip('/')}"
    return DEFAULT_HOST


async def _check_server(base: str, quiet: bool = False) -> bool:
    try:
        import httpx

        async with httpx.AsyncClient() as c:
            try:
                await c.get(base, timeout=3)
            except httpx.ConnectError:
                if not quiet:
                    logging.getLogger("a2a-cli").error("Cannot connect to %s", base)
                return False
    except ImportError:
        pass
    return True


# Restore terminal on exit / signals ---------------------------------------
def _exit_handler(*_a):  # noqa: ANN001
    restore_terminal()
    sys.exit(0)


atexit.register(restore_terminal)
for _sig in (signal.SIGINT, signal.SIGTERM) + (
    (signal.SIGQUIT,) if hasattr(signal, "SIGQUIT") else ()
):  # type: ignore[misc]
    signal.signal(_sig, _exit_handler)  # type: ignore[arg-type]

# ────────────────────────────────────────────────────────────────────────────
# Typer application
# ────────────────────────────────────────────────────────────────────────────
app = typer.Typer(help="A2A CLI – chat & task control for your A2A server")


@app.callback(invoke_without_command=True)
def _common(  # noqa: D401 – Typer callback
    ctx: typer.Context,
    config_file: str = typer.Option("~/.a2a/config.json", help="Config JSON"),
    server: str | None = typer.Option(None, help="Server URL or name from config"),
    debug: bool = typer.Option(False, help="Debug output"),
    quiet: bool = typer.Option(False, help="Silence non-errors"),
    log_level: str = typer.Option("INFO", help="Log level when not in --debug/--quiet"),
):
    """Global options.  If no sub-command is given we drop into chat mode."""
    _setup_logging(debug, quiet, log_level)

    cfg_path = os.path.expanduser(config_file)
    base_url = None
    if server:
        if server.startswith(("http://", "https://")):
            base_url = server.rstrip("/")
        else:
            if os.path.exists(cfg_path):
                try:
                    base_url = json.load(open(cfg_path)).get("servers", {}).get(server)
                except Exception:  # noqa: BLE001
                    pass
            base_url = base_url or _resolve_base(server)

    ctx.obj = {"cfg": cfg_path, "base": base_url, "debug": debug, "quiet": quiet}

    if ctx.invoked_subcommand is None:
        try:
            asyncio.run(handle_chat_mode(base_url, cfg_path, CLI_SESSION_ID))
        finally:
            restore_terminal()
        raise typer.Exit()

# ────────────────────────────────────────────────────────────────────────────
# send command
# ────────────────────────────────────────────────────────────────────────────
@app.command()
def send(
    text: str = typer.Argument(..., help="User message"),
    prefix: str | None = typer.Option(None, help="Handler mount or URL"),
    wait: bool = typer.Option(False, help="Wait & stream"),
    color: bool = typer.Option(True, help="Pretty colours"),
):
    """Send *text* as a new task; attach the CLI session id."""
    base = _resolve_base(prefix)
    rpc_url, events_url = base + RPC_SUFFIX, base + EVENTS_SUFFIX

    if not asyncio.run(_check_server(base, quiet=False)):
        raise typer.Exit(1)

    params = TaskSendParams(
        id=str(uuid.uuid4()),
        session_id=CLI_SESSION_ID,
        message=Message(role="user", parts=[TextPart(type="text", text=text)]),
    )

    http_client = A2AClient.over_http(rpc_url)
    try:
        task = asyncio.run(http_client.send_task(params))
        if not wait:
            display_task_info(task, color)
    except JSONRPCError as exc:
        logging.getLogger("a2a-cli").error("Send failed: %s", exc)
        raise typer.Exit(1)

    if not wait:
        return

    # ── streaming view ────────────────────────────────────────────────
    sse_client = A2AClient.over_sse(rpc_url, events_url)

    async def _stream() -> None:
        from rich.live import Live
        from rich.text import Text

        console = Console()
        status_line = ""
        artifact_lines: list[str] = []

        with Live("", refresh_per_second=4, console=console) as live:
            async for evt in sse_client.send_subscribe(params):
                if isinstance(evt, TaskStatusUpdateEvent):
                    status_line = format_status_event(evt)
                    if evt.final:
                        live.update(Text.from_markup(status_line + "\n" + "\n".join(artifact_lines)))
                        break
                elif isinstance(evt, TaskArtifactUpdateEvent):
                    artifact_lines.append(format_artifact_event(evt))
                else:
                    artifact_lines.append(f"Unknown event: {type(evt).__name__}")

                live.update(Text.from_markup(status_line + "\n" + "\n".join(artifact_lines)))

    asyncio.run(_stream())

# ────────────────────────────────────────────────────────────────────────────
# get command
# ────────────────────────────────────────────────────────────────────────────
@app.command()
def get(
    id: str = typer.Argument(..., help="Task id"),
    prefix: str | None = typer.Option(None, help="Handler mount or URL"),
    json_output: bool = typer.Option(False, "--json", help="Raw JSON"),
    color: bool = typer.Option(True, help="Colourful output"),
):
    base = _resolve_base(prefix)
    rpc_url = base + RPC_SUFFIX

    if not asyncio.run(_check_server(base)):
        raise typer.Exit(1)

    task = asyncio.run(A2AClient.over_http(rpc_url).get_task(TaskQueryParams(id=id)))
    if json_output:
        print(json.dumps(task.model_dump(by_alias=True), indent=2))
    else:
        display_task_info(task, color)

# ────────────────────────────────────────────────────────────────────────────
# cancel command
# ────────────────────────────────────────────────────────────────────────────
@app.command()
def cancel(
    id: str = typer.Argument(..., help="Task id"),
    prefix: str | None = typer.Option(None, help="Handler mount or URL"),
):
    base = _resolve_base(prefix)
    rpc_url = base + RPC_SUFFIX

    if not asyncio.run(_check_server(base)):
        raise typer.Exit(1)

    asyncio.run(A2AClient.over_http(rpc_url).cancel_task(TaskIdParams(id=id)))
    print(f"[green]Canceled task {id}[/green]")

# ────────────────────────────────────────────────────────────────────────────
# watch command
# ────────────────────────────────────────────────────────────────────────────
@app.command()
def watch(
    id: str | None = typer.Argument(None, help="Existing task id to watch"),
    text: str | None = typer.Option(None, help="Send new text & watch"),
    prefix: str | None = typer.Option(None, help="Handler mount or URL"),
):
    base = _resolve_base(prefix)
    rpc_url, events_url = base + RPC_SUFFIX, base + EVENTS_SUFFIX
    if not asyncio.run(_check_server(base)):
        raise typer.Exit(1)

    sse_client = A2AClient.over_sse(rpc_url, events_url)

    if text:
        params = TaskSendParams(
            id=str(uuid.uuid4()),
            session_id=CLI_SESSION_ID,
            message=Message(role="user", parts=[TextPart(type="text", text=text)]),
        )
        stream = sse_client.send_subscribe(params)
    elif id:
        stream = sse_client.resubscribe(TaskQueryParams(id=id))
    else:
        print("[red]Specify an --id or --text[/red]")
        return

    # ── streaming view ────────────────────────────────────────────────
    async def _run() -> None:
        from rich.live import Live
        from rich.text import Text

        console = Console()
        status_line = ""
        artifact_lines: list[str] = []

        with Live("", refresh_per_second=4, console=console) as live:
            async for evt in stream:
                if isinstance(evt, TaskStatusUpdateEvent):
                    status_line = format_status_event(evt)
                    if evt.final:
                        live.update(Text.from_markup(status_line + "\n" + "\n".join(artifact_lines)))
                        break
                elif isinstance(evt, TaskArtifactUpdateEvent):
                    artifact_lines.append(format_artifact_event(evt))
                else:
                    artifact_lines.append(f"Unknown event: {type(evt).__name__}")

                live.update(Text.from_markup(status_line + "\n" + "\n".join(artifact_lines)))

    asyncio.run(_run())

# ────────────────────────────────────────────────────────────────────────────
# chat shortcut
# ────────────────────────────────────────────────────────────────────────────
@app.command()
def chat(
    server: str | None = typer.Option(None, help="Server URL"),
    config_file: str = typer.Option("~/.a2a/config.json", help="Config JSON"),
):
    asyncio.run(handle_chat_mode(server, os.path.expanduser(config_file), CLI_SESSION_ID))

# ────────────────────────────────────────────────────────────────────────────
# stdio (JSON-RPC over stdin/stdout) – mostly for chaining
# ────────────────────────────────────────────────────────────────────────────
@app.command()
def stdio():
    """Run the client wired to stdin/stdout (JSON-RPC)."""
    client = A2AClient.over_stdio()

    async def _run() -> None:
        async for message in client.transport.stream():
            # Extend here if you want to hook the CLI into shell pipelines etc.
            ...

    asyncio.run(_run())

# ────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        app()
    except KeyboardInterrupt:
        logging.getLogger("a2a-cli").debug("Interrupted by user")
    finally:
        restore_terminal()
