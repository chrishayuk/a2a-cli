#!/usr/bin/env python3
# a2a_cli/a2a_client.py
"""
High-level A2A client (transport-agnostic).

Key points
──────────
* `_READ_TIMEOUT_S` – set to **90 seconds**; change it once and every transport
  inherits it.
* Unified `_coerce_stream_event` converts raw transport payloads into real
  `TaskStatusUpdateEvent` / `TaskArtifactUpdateEvent` instances.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Dict, Type, Union

import httpx                             # new – for Timeout helper

from a2a_json_rpc.spec import (
    Message,
    Task,
    TaskArtifactUpdateEvent,
    TaskIdParams,
    TaskPushNotificationConfig,
    TaskQueryParams,
    TaskSendParams,
    TaskStatusUpdateEvent,
)
from a2a_json_rpc.transport import JSONRPCTransport

from a2a_cli.transport.http import JSONRPCHTTPClient
from a2a_cli.transport.sse import JSONRPCSSEClient
from a2a_cli.transport.websocket import JSONRPCWebSocketClient

logger = logging.getLogger("a2a-cli")

# ────────────────────────────────────────────────────────────────────────────
# single source-of-truth for all network time-outs
# ────────────────────────────────────────────────────────────────────────────
_READ_TIMEOUT_S = 90.0        # ← bump this if your backend can stall longer
_HTTPX_TIMEOUT = httpx.Timeout(
    connect=10.0,
    read=_READ_TIMEOUT_S,
    write=30.0,
    pool=10.0,
)

# ════════════════════════════════════════════════════════════════════════════
# client
# ════════════════════════════════════════════════════════════════════════════
class A2AClient:
    """Agent-to-Agent high-level client (transport-agnostic)."""

    # ── construction helpers ────────────────────────────────────────────
    def __init__(self, transport: JSONRPCTransport) -> None:
        self.transport = transport

    @classmethod
    def over_http(cls: Type["A2AClient"], endpoint: str) -> "A2AClient":
        return cls(JSONRPCHTTPClient(endpoint, timeout=_HTTPX_TIMEOUT))

    @classmethod
    def over_ws(cls: Type["A2AClient"], url: str) -> "A2AClient":
        return cls(JSONRPCWebSocketClient(url, timeout=_HTTPX_TIMEOUT))

    @classmethod
    def over_sse(
        cls: Type["A2AClient"],
        endpoint: str,
        sse_endpoint: str | None = None,
    ) -> "A2AClient":
        return cls(
            JSONRPCSSEClient(
                endpoint,
                sse_endpoint=sse_endpoint,
                timeout=_HTTPX_TIMEOUT,
            )
        )

    # ── basic RPC wrappers ──────────────────────────────────────────────
    async def send_task(self, params: TaskSendParams) -> Task:
        raw = await self.transport.call(
            "tasks/send", params.model_dump(mode="json", exclude_none=True, by_alias=True)
        )
        return Task.model_validate(raw)

    async def get_task(self, params: TaskQueryParams) -> Task:
        raw = await self.transport.call(
            "tasks/get", params.model_dump(mode="json", exclude_none=True, by_alias=True)
        )
        return Task.model_validate(raw)

    async def cancel_task(self, params: TaskIdParams) -> None:
        await self.transport.call(
            "tasks/cancel", params.model_dump(mode="json", exclude_none=True, by_alias=True)
        )

    async def set_push_notification(
        self, params: TaskPushNotificationConfig
    ) -> TaskPushNotificationConfig:
        raw = await self.transport.call(
            "tasks/pushNotification/set",
            params.model_dump(mode="json", exclude_none=True, by_alias=True),
        )
        return TaskPushNotificationConfig.model_validate(raw)

    async def get_push_notification(
        self, params: TaskIdParams
    ) -> TaskPushNotificationConfig:
        raw = await self.transport.call(
            "tasks/pushNotification/get",
            params.model_dump(mode="json", exclude_none=True, by_alias=True),
        )
        return TaskPushNotificationConfig.model_validate(raw)

    # ── helper to normalise stream events ───────────────────────────────
    @staticmethod
    def _coerce_stream_event(  # noqa: D401
        evt: Dict[str, Any]
    ) -> Union[TaskStatusUpdateEvent, TaskArtifactUpdateEvent, Dict[str, Any]]:
        """Convert raw transport payload to proper spec objects."""
        # HTTP & WS transports wrap the payload: {"method":"tasks/event","params":{…}}
        if evt.get("method") == "tasks/event":
            evt = evt["params"]

        # transport.http adds `type: status|artifact` – drop before validation
        if "status" in evt:
            return TaskStatusUpdateEvent.model_validate(
                {k: v for k, v in evt.items() if k != "type"}
            )
        if "artifact" in evt:
            return TaskArtifactUpdateEvent.model_validate(
                {k: v for k, v in evt.items() if k != "type"}
            )
        return evt  # unknown – let caller decide

    # ── streaming helpers ───────────────────────────────────────────────
    async def send_subscribe(
        self, params: TaskSendParams
    ) -> AsyncIterator[Union[TaskStatusUpdateEvent, TaskArtifactUpdateEvent]]:
        await self.transport.call(
            "tasks/sendSubscribe",
            params.model_dump(mode="json", exclude_none=True, by_alias=True),
        )
        async for raw in self.transport.stream():
            try:
                yield self._coerce_stream_event(raw)
            except Exception:      # noqa: BLE001
                logger.exception("Failed to parse sendSubscribe event")

    async def resubscribe(
        self, params: TaskQueryParams
    ) -> AsyncIterator[Union[TaskStatusUpdateEvent, TaskArtifactUpdateEvent]]:
        await self.transport.call(
            "tasks/resubscribe",
            params.model_dump(mode="json", exclude_none=True, by_alias=True),
        )
        async for raw in self.transport.stream():
            try:
                yield self._coerce_stream_event(raw)
            except Exception:      # noqa: BLE001
                logger.exception("Failed to parse resubscribe event")
