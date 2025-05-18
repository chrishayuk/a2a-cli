#!/usr/bin/env python3
# a2a_cli/chat/chat_context.py
"""
Chat context for the A2A client interface.

Manages the client, connection, and state information.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional
from uuid import uuid4

from a2a_cli.a2a_client import A2AClient
from a2a_json_rpc.json_rpc_errors import JSONRPCError
from a2a_json_rpc.spec import TaskQueryParams

logger = logging.getLogger("a2a-client")


class ChatContext:
    """Holds all shared state for the interactive chat UI."""

    # ------------------------------------------------------------------ #
    # construction & initialisation                                      #
    # ------------------------------------------------------------------ #
    def __init__(
        self,
        base_url: Optional[str] = None,
        config_file: Optional[str] = None,
        *,
        session_id: Optional[str] = None,
    ) -> None:
        # Connection info ------------------------------------------------
        self.base_url = base_url or "http://localhost:8000"
        self.config_file = config_file

        # Shared conversation identifier ---------------------------------
        self.session_id = session_id or uuid4().hex

        # Client handles -------------------------------------------------
        self.client: Optional[A2AClient] = None
        self.streaming_client: Optional[A2AClient] = None

        # Flags ----------------------------------------------------------
        self.exit_requested = False
        self.verbose_mode = False
        self.debug_mode = False

        # Misc runtime state --------------------------------------------
        self.command_history: List[str] = []
        self.server_names: Dict[str, str] = {}       # name -> url (from config)
        self.last_task_id: Optional[str] = None

        # NEW – all artifacts we have seen this CLI run
        self.artifact_index: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------ #
    # public API                                                         #
    # ------------------------------------------------------------------ #
    async def initialize(self) -> bool:
        """Load config (if any) **and** attempt to connect to the server."""
        if self.config_file:
            try:
                self._load_config()
            except Exception as exc:  # noqa: BLE001
                logger.error("Error loading config: %s", exc)
                return False

        try:
            await self._connect_to_server()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Error connecting to server: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    # private helpers                                                    #
    # ------------------------------------------------------------------ #
    def _load_config(self) -> None:
        """Read the JSON config file and populate *server_names*."""
        config_path = os.path.expanduser(self.config_file)  # type: ignore[arg-type]
        if not os.path.exists(config_path):
            logger.warning("Config file not found: %s", config_path)
            return

        with open(config_path, encoding="utf-8") as fp:
            try:
                config = json.load(fp)
            except json.JSONDecodeError:
                logger.error("Invalid JSON in config file: %s", config_path)
                return

        self.server_names = config.get("servers", {})
        logger.info("Loaded %d servers from config", len(self.server_names))

        if not self.base_url and self.server_names:
            self.base_url = next(iter(self.server_names.values()))
            logger.info("Using first server from config: %s", self.base_url)

    async def _connect_to_server(self) -> None:
        """Establish HTTP + SSE clients and perform a quick ping."""
        rpc_url = f"{self.base_url.rstrip('/')}/rpc"
        events_url = f"{self.base_url.rstrip('/')}/events"

        # plain HTTP -----------------------------------------------------
        self.client = A2AClient.over_http(rpc_url)
        logger.debug("Testing connection to %s…", rpc_url)
        try:
            await self.client.get_task(TaskQueryParams(id="ping-test-000"))
        except JSONRPCError as exc:
            if "not found" in str(exc).lower():
                logger.info("Successfully connected to %s", self.base_url)
            else:
                logger.warning("Connected but ping produced: %s", exc)

        # merged-SSE / streaming ----------------------------------------
        self.streaming_client = A2AClient.over_sse(rpc_url, events_url)

    # ------------------------------------------------------------------ #
    # dictionary helpers (used by slash-command layer)                   #
    # ------------------------------------------------------------------ #
    def to_dict(self) -> Dict[str, Any]:
        """Snapshot the mutable state into a plain dict."""
        return {
            "base_url": self.base_url,
            "client": self.client,
            "streaming_client": self.streaming_client,
            "verbose_mode": self.verbose_mode,
            "debug_mode": self.debug_mode,
            "exit_requested": self.exit_requested,
            "command_history": self.command_history,
            "server_names": self.server_names,
            "last_task_id": self.last_task_id,
            "session_id": self.session_id,
            "artifact_index": self.artifact_index,
        }

    def update_from_dict(self, ctx: Dict[str, Any]) -> None:  # noqa: C901
        """Apply updates coming back from command helpers."""
        # Scalars --------------------------------------------------------
        for key in (
            "base_url",
            "verbose_mode",
            "debug_mode",
            "exit_requested",
            "last_task_id",
        ):
            if key in ctx:
                setattr(self, key, ctx[key])

        # Containers -----------------------------------------------------
        if "command_history" in ctx:
            self.command_history = list(ctx["command_history"])
        if "server_names" in ctx:
            self.server_names = dict(ctx["server_names"])

        # Merge-append any new artifacts
        if "artifact_index" in ctx:
            for art in ctx["artifact_index"]:
                if art not in self.artifact_index:
                    self.artifact_index.append(art)

        # Clients --------------------------------------------------------
        if "client" in ctx:
            self.client = ctx["client"]
        if "streaming_client" in ctx:
            self.streaming_client = ctx["streaming_client"]

        # NOTE: session_id is immutable – any attempt to overwrite is ignored.

    # ------------------------------------------------------------------ #
    # cleanup                                                            #
    # ------------------------------------------------------------------ #
    async def close(self) -> None:
        """Close both transports if they expose `.close()`."""
        if self.streaming_client and hasattr(self.streaming_client.transport, "close"):
            await self.streaming_client.transport.close()

        if self.client and hasattr(self.client.transport, "close"):
            await self.client.transport.close()
