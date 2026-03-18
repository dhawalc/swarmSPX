"""REST API endpoints for the SwarmSPX web dashboard."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException

from swarmspx.web.state import CycleState

log = logging.getLogger(__name__)

AGENTS_YAML = Path(__file__).resolve().parents[2] / "config" / "agents.yaml"


def create_router(state: CycleState, engine: Any) -> APIRouter:
    """Factory that returns an APIRouter bound to *state* and *engine*."""

    router = APIRouter(prefix="/api")

    @router.get("/status")
    async def status() -> dict:
        """Return the current cycle state snapshot."""
        return state.get_snapshot()

    @router.get("/agents")
    async def agents() -> dict:
        """Return agent definitions parsed from config/agents.yaml."""
        try:
            with open(AGENTS_YAML) as f:
                data = yaml.safe_load(f)
            return data
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="agents.yaml not found")

    @router.post("/cycle/trigger")
    async def trigger_cycle() -> dict:
        """Trigger a new simulation cycle (non-blocking)."""
        snap = state.get_snapshot()
        if snap.get("status") == "running" or snap.get("status") == "deliberating":
            raise HTTPException(status_code=409, detail="Cycle already in progress")

        asyncio.ensure_future(engine.run_cycle())
        return {"message": "Cycle triggered", "cycle_id": (snap.get("cycle_id") or 0) + 1}

    return router
