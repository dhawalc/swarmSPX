"""FastAPI application for the SwarmSPX web dashboard.

Usage (standalone)::

    uvicorn swarmspx.web.app:create_app --factory --host 0.0.0.0 --port 8000

Or import ``create_app`` and pass your own EventBus / engine.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from dotenv import load_dotenv
load_dotenv()

from swarmspx.events import EventBus
from swarmspx.web.state import CycleState
from swarmspx.web.ws_manager import WebSocketManager
from swarmspx.web.routes import create_router
from swarmspx.alerts.dispatcher import AlertDispatcher

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(
    bus: EventBus | None = None,
    engine: Any | None = None,
    settings_path: str = "config/settings.yaml",
) -> FastAPI:
    """Build and return a fully-configured FastAPI application.

    Parameters
    ----------
    bus:
        An existing EventBus.  If *None* a new one is created.
    engine:
        A ``SwarmSPXEngine`` (or compatible).  If *None* the app will
        import and instantiate one during startup.
    """

    bus = bus or EventBus()
    state = CycleState()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal engine

        # Lazily create the engine if none was injected
        if engine is None:
            from swarmspx.engine import SwarmSPXEngine
            engine = SwarmSPXEngine(settings_path=settings_path, bus=bus)

        # Bind engine to the router closure
        app.state.engine = engine
        app.state.bus = bus
        app.state.cycle_state = state

        # Start background consumers
        state.start(bus)
        ws_mgr = WebSocketManager(bus, state)
        ws_mgr.start()
        app.state.ws_manager = ws_mgr

        # Start alert dispatcher (Telegram + Slack)
        alert_dispatcher = AlertDispatcher(bus, min_confidence=70.0)
        alert_dispatcher.start()
        app.state.alert_dispatcher = alert_dispatcher

        log.info("SwarmSPX dashboard started")
        yield

        # Shutdown
        alert_dispatcher.stop()
        await ws_mgr.stop()
        await state.stop()
        log.info("SwarmSPX dashboard stopped")

    app = FastAPI(
        title="SwarmSPX Dashboard",
        version="1.0.0",
        lifespan=lifespan,
    )

    # REST endpoints
    app.include_router(create_router(state, engine))

    # WebSocket
    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        mgr: WebSocketManager = app.state.ws_manager
        await mgr.connect(ws)
        try:
            while True:
                # Keep the connection alive; we only push data server->client
                await ws.receive_text()
        except WebSocketDisconnect:
            mgr.disconnect(ws)

    # Static files
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    return app
