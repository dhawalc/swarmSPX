"""WebSocket connection manager.

Subscribes to the EventBus, fans events out to every connected browser
client as JSON.  New connections immediately receive a ``full_state``
message so the UI can hydrate without waiting for the next event.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from swarmspx.events import EventBus
from swarmspx.web.state import CycleState

log = logging.getLogger(__name__)


class WebSocketManager:
    """Manages active WebSocket connections and event fan-out."""

    def __init__(self, bus: EventBus, state: CycleState) -> None:
        self._bus = bus
        self._state = state
        self._connections: list[WebSocket] = []
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Begin listening to the EventBus."""
        self._queue = self._bus.subscribe()
        self._task = asyncio.ensure_future(self._relay_loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._bus.unsubscribe(self._queue)

    # ------------------------------------------------------------------
    # Connection handling
    # ------------------------------------------------------------------

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        # Immediately send the full state snapshot so the UI can hydrate
        snapshot = self._state.get_snapshot()
        await self._send(ws, {"type": "full_state", "data": snapshot})
        log.info("WebSocket client connected (%d total)", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._connections:
            self._connections.remove(ws)
        log.info("WebSocket client disconnected (%d total)", len(self._connections))

    # ------------------------------------------------------------------
    # Internal relay loop
    # ------------------------------------------------------------------

    async def _relay_loop(self) -> None:
        """Consume events from EventBus and broadcast to all clients."""
        while True:
            event = await self._queue.get()
            payload = {"type": event.event_type, "data": event.to_dict()}
            await self._broadcast(payload)

    async def _broadcast(self, payload: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        raw = json.dumps(payload, default=str)
        for ws in self._connections:
            try:
                await ws.send_text(raw)
            except (WebSocketDisconnect, RuntimeError, Exception):
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    @staticmethod
    async def _send(ws: WebSocket, payload: dict[str, Any]) -> None:
        try:
            await ws.send_text(json.dumps(payload, default=str))
        except Exception:
            pass
