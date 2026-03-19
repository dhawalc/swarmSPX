"""In-memory cycle state tracker.

Consumes EventBus events and maintains a snapshot dict of the current
cycle so any component (REST endpoint, WebSocket manager) can grab
the latest state without coupling to the event stream.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from swarmspx.events import EventBus


class CycleState:
    """Tracks the rolling state of the current (or most recent) cycle."""

    def __init__(self) -> None:
        self._state: dict[str, Any] = {
            "status": "idle",
            "cycle_id": None,
            "market_context": None,
            "current_round": 0,
            "total_rounds": 5,
            "votes": {},          # agent_id -> latest vote dict
            "round_summaries": [],  # per-round vote_counts
            "consensus": None,
            "trade_card": None,
            "error": None,
            "last_updated": time.time(),
        }
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_snapshot(self) -> dict[str, Any]:
        """Return a JSON-serialisable copy of the current state."""
        return {**self._state, "last_updated": time.time()}

    def start(self, bus: EventBus) -> None:
        """Begin consuming events from *bus* in the background."""
        self._queue = bus.subscribe()
        self._bus = bus
        self._task = asyncio.ensure_future(self._consume())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._bus.unsubscribe(self._queue)

    # ------------------------------------------------------------------
    # Internal event loop
    # ------------------------------------------------------------------

    async def _consume(self) -> None:
        while True:
            event = await self._queue.get()
            handler = getattr(self, f"_on_{event.event_type}", None)
            if handler:
                handler(event.to_dict())
            self._state["last_updated"] = time.time()

    # ------------------------------------------------------------------
    # Per-event handlers
    # ------------------------------------------------------------------

    def _on_cycle_started(self, d: dict) -> None:
        self._state.update(
            status="running",
            cycle_id=d["cycle_id"],
            market_context=None,
            current_round=0,
            votes={},
            round_summaries=[],
            consensus=None,
            trade_card=None,
            error=None,
        )

    def _on_market_data_fetched(self, d: dict) -> None:
        self._state["market_context"] = d.get("market_context")

    def _on_round_started(self, d: dict) -> None:
        self._state["current_round"] = d.get("round_num", 0)
        self._state["total_rounds"] = d.get("total_rounds", 5)
        self._state["status"] = "deliberating"

    def _on_agent_voted(self, d: dict) -> None:
        agent_id = d.get("agent_id", "")
        self._state["votes"][agent_id] = {
            "agent_id": agent_id,
            "agent_name": d.get("agent_name", ""),
            "tribe": d.get("tribe", ""),
            "direction": d.get("direction", ""),
            "conviction": d.get("conviction", 0),
            "reasoning": d.get("reasoning", ""),
            "trade_idea": d.get("trade_idea", ""),
            "changed_from": d.get("changed_from"),
            "round_num": d.get("round_num", 0),
        }

    def _on_round_completed(self, d: dict) -> None:
        self._state["round_summaries"].append({
            "round_num": d.get("round_num", 0),
            "vote_counts": d.get("vote_counts", {}),
            "votes": d.get("votes", []),
        })

    def _on_consensus_reached(self, d: dict) -> None:
        self._state["consensus"] = d.get("consensus")
        self._state["status"] = "consensus"

    def _on_trade_card_generated(self, d: dict) -> None:
        self._state["trade_card"] = d.get("trade_card")
        self._state["status"] = "complete"

    def _on_cycle_completed(self, d: dict) -> None:
        self._state["status"] = "idle"

    def _on_outcome_resolved(self, d: dict) -> None:
        outcomes = self._state.setdefault("recent_outcomes", [])
        outcomes.insert(0, {
            "signal_id": d.get("signal_id"),
            "direction": d.get("direction"),
            "outcome": d.get("outcome"),
            "outcome_pct": d.get("outcome_pct"),
        })
        # Keep last 10 outcomes in memory
        self._state["recent_outcomes"] = outcomes[:10]

    def _on_engine_error(self, d: dict) -> None:
        self._state["error"] = d.get("message")
        self._state["status"] = "error"
