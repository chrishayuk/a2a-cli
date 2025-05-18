#!/usr/bin/env python3
"""List / preview / download cached artifacts."""
from __future__ import annotations

import base64
import os
from typing import Any, Dict, List

from rich import print    # pylint: disable=redefined-builtin
from rich.console import Console
from rich.panel import Panel
from rich.table import Table 

from a2a_cli.chat.commands import register_command
from a2a_cli.chat.commands.tasks import _display_artifact   # re-use helper


def _get_index(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    return ctx.get("artifact_index", [])


# ────────────────────────────────────────────────────────────────────────────
# /artifacts  (list or show/download)
# ────────────────────────────────────────────────────────────────────────────
async def cmd_artifacts(cmd_parts: List[str], context: Dict[str, Any]) -> bool:
    """
    • `/artifacts`            → list all cached artefacts this CLI run
    • `/artifacts 5`          → pretty-print artefact #5
    • `/artifacts 5 save`     → write artefact #5 to disk (auto-filename)
    """
    console = Console()
    arts: List[Dict[str, Any]] = context.get("artifact_index", [])

    # ---------- list ---------------------------------------------------
    if len(cmd_parts) == 1:
        if not arts:
            print("[yellow]No artifacts collected in this session yet.[/yellow]")
            return True

        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("#", style="dim", width=4)
        table.add_column("Task ID")
        table.add_column("Name")
        table.add_column("MIME")

        for i, info in enumerate(arts, 1):
            table.add_row(str(i), info["task_id"][:8] + "…", info["name"], info["mime"])

        console.print(Panel(table, title=f"Artifacts ({len(arts)})"))
        return True

    # ---------- parse index -------------------------------------------
    try:
        idx = int(cmd_parts[1])
        assert 1 <= idx <= len(arts)
    except (ValueError, AssertionError):
        print("[red]Usage: /artifacts [index] [save][/red]")
        return True

    art_info = arts[idx - 1]
    art = art_info["artifact"]

    # ---------- just show ---------------------------------------------
    if len(cmd_parts) == 2 or cmd_parts[2].lower() in {"show", "view"}:
        _display_artifact(art, console)
        return True

    # ---------- save to file ------------------------------------------
    if cmd_parts[2].lower() in {"save", "download"}:
        # pick first binary/text part – this keeps it simple
        part = art.parts[0]
        filename = art_info["name"]
        if "." not in filename:
            # guess extension from MIME
            ext = {
                "text/plain": ".txt",
                "image/png": ".png",
                "image/jpeg": ".jpg",
                "application/json": ".json",
            }.get(art_info["mime"], ".bin")
            filename += ext

        try:
            mode = "wb" if hasattr(part, "data") else "w"
            with open(filename, mode) as fp:
                fp.write(getattr(part, "data", getattr(part, "text", "")).encode()
                         if mode == "wb" else getattr(part, "text", ""))
            print(f"[green]Saved to {filename}[/green]")
        except Exception as exc:  # noqa: BLE001
            print(f"[red]Failed to save artifact:[/red] {exc}")
        return True

    # ---------- anything else -----------------------------------------
    print("[red]Unknown sub-command for /artifacts[/red]")
    return True


register_command("/artifacts", cmd_artifacts)
