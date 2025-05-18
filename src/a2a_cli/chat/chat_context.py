#!/usr/bin/env python3
# a2a_cli/chat/chat_context.py
"""
Chat context for the A2A client interface.

Manages the client, connection, and state information.
"""
import asyncio
import logging
import os
import json
from typing import Dict, Any, Optional, List
from uuid import uuid4

# a2a client imports
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
        """Create a new chat context.

        Parameters
        ----------
        base_url
            Base URL of the A2A server. Defaults to *http://localhost:8000*.
        config_file
            Optional path to a JSON config with named servers.
        session_id
            The **process‑wide** UUID generated in *cli.py*.  Every task we
            emit will carry exactly this value so the server can thread the
            conversation.  If ``None`` we fall back to a fresh UUID (makes the
            class usable in tests).
        """
        # Connection info ------------------------------------------------
        self.base_url = base_url or "http://localhost:8000"
        self.config_file = config_file

        # Shared conversation identifier ---------------------------------
        self.session_id = session_id or uuid4().hex

        # Client handles --------------------------------------------------
        self.client: Optional[A2AClient] = None
        self.streaming_client: Optional[A2AClient] = None

        # Flags -----------------------------------------------------------
        self.exit_requested = False
        self.verbose_mode = False
        self.debug_mode = False

        # Misc state ------------------------------------------------------
        self.command_history: List[str] = []
        self.server_names: Dict[str, str] = {}  # name -> url (from config)
        self.last_task_id: Optional[str] = None

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

        with open(config_path, "r", encoding="utf-8") as fp:
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

        # Plain HTTP client ----------------------------------------------
        self.client = A2AClient.over_http(rpc_url)
        logger.debug("Testing connection to %s…", rpc_url)
        try:
            await self.client.get_task(TaskQueryParams(id="ping-test-000"))
        except JSONRPCError as exc:
            if "not found" in str(exc).lower():
                logger.info("Successfully connected to %s", self.base_url)
            else:
                logger.warning("Connected but ping produced: %s", exc)

        # SSE / streaming client -----------------------------------------
        self.streaming_client = A2AClient.over_sse(rpc_url, events_url)

    # ------------------------------------------------------------------ #
    # dictionary helpers for command system                              #
    # ------------------------------------------------------------------ #
    def to_dict(self) -> Dict[str, Any]:
        """Return a plain dict snapshot of the mutable state."""
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
        }

    def update_from_dict(self, ctx: Dict[str, Any]) -> None:  # noqa: C901 - long but simple
        """Apply updates coming back from command helpers."""
        # Simple scalar fields -------------------------------------------
        for key in (
            "base_url",
            "verbose_mode",
            "debug_mode",
            "exit_requested",
            "last_task_id",
        ):
            if key in ctx:
                setattr(self, key, ctx[key])

        # Containers ------------------------------------------------------
        if "command_history" in ctx:
            self.command_history = list(ctx["command_history"])  # copy
        if "server_names" in ctx:
            self.server_names = dict(ctx["server_names"])

        # Clients ---------------------------------------------------------
        if "client" in ctx:
            self.client = ctx["client"]
        if "streaming_client" in ctx:
            self.streaming_client = ctx["streaming_client"]

        # Session-id is immutable on purpose - ignore any attempt to overwrite

    # ------------------------------------------------------------------ #
    # cleanup                                                             #
    # ------------------------------------------------------------------ #
    async def close(self) -> None:
        """Close both transport layers, if they expose a .close()."""
        if self.streaming_client and hasattr(self.streaming_client.transport, "close"):
            await self.streaming_client.transport.close()

        if self.client and hasattr(self.client.transport, "close"):
            await self.client.transport.close()
