"""REST API endpoints for the SwarmSPX web dashboard."""

from __future__ import annotations

import asyncio
import logging
import random
from pathlib import Path
from typing import Any, Optional

import yaml
from fastapi import APIRouter, HTTPException, Request

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

    @router.get("/signals")
    async def signals() -> dict:
        """Return recent signals with outcomes."""
        return {"signals": engine.db.get_recent_signals(limit=20)}

    @router.get("/stats")
    async def stats() -> dict:
        """Return aggregate signal statistics."""
        return engine.db.get_signal_stats()

    @router.get("/agents/custom")
    async def list_custom_agents() -> dict:
        """Return currently loaded custom agents."""
        return {"agents": engine.forge.get_custom_agents()}

    @router.post("/agents/custom")
    async def add_custom_agent(body: dict) -> dict:
        """Add a new custom agent to the swarm."""
        try:
            added = engine.forge.add_custom_agent(body)
            return {"status": "added", "agent": added}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.delete("/agents/custom/{agent_id}")
    async def delete_custom_agent(agent_id: str) -> dict:
        """Remove a custom agent from the swarm."""
        removed = engine.forge.remove_custom_agent(agent_id)
        if not removed:
            raise HTTPException(status_code=404, detail=f"Custom agent '{agent_id}' not found")
        return {"status": "removed", "agent_id": agent_id}

    @router.post("/cycle/trigger")
    async def trigger_cycle() -> dict:
        """Trigger a new simulation cycle (non-blocking)."""
        snap = state.get_snapshot()
        if snap.get("status") == "running" or snap.get("status") == "deliberating":
            raise HTTPException(status_code=409, detail="Cycle already in progress")

        asyncio.ensure_future(engine.run_cycle())
        return {"message": "Cycle triggered", "cycle_id": (snap.get("cycle_id") or 0) + 1}

    # ── Risk subsystem ──────────────────────────────────────────────────
    # Dashboards consume /api/risk to show kill-switch banner + sizing cap
    # + recent outcome counts. Manual ops via POST endpoints.

    @router.get("/risk")
    async def get_risk_status() -> dict:
        """Return killswitch state, sizing cap, and recent gated signals."""
        ks = engine.killswitch.state
        cap = engine.sizer.get_today_cap()

        try:
            signals = engine.db.get_recent_signals(limit=20)
        except Exception:
            signals = []
        from collections import Counter
        outcome_counts = dict(Counter(s.get("outcome", "unknown") for s in signals))

        try:
            stats = engine.db.get_signal_stats()
        except Exception:
            stats = {}

        return {
            "killswitch": {
                "tripped": bool(ks.get("tripped")),
                "triggered_by": ks.get("triggered_by", ""),
                "triggered_reason": ks.get("triggered_reason", ""),
                "triggered_at": ks.get("triggered_at", ""),
                "auto_clear_at": ks.get("auto_clear_at"),
                "trigger_count": ks.get("trigger_count", 0),
            },
            "sizing": cap,
            "recent_outcomes": outcome_counts,
            "all_time_stats": stats,
        }

    @router.post("/risk/trip")
    async def trip_risk(body: dict) -> dict:
        """Manually trip the kill switch. Body: {"reason": "<text>"}."""
        reason = (body or {}).get("reason", "manual via /api/risk/trip")
        engine.killswitch.trip("manual", reason)
        log.warning("KILL_SWITCH_TRIPPED via /api/risk/trip: %s", reason)
        return {"status": "tripped", "reason": reason}

    @router.post("/risk/reset")
    async def reset_risk(body: dict) -> dict:
        """Manually clear the kill switch. Body (optional): {"by": "<who>"}."""
        by = (body or {}).get("by", "api")
        if not engine.killswitch.is_tripped():
            return {"status": "noop", "message": "kill switch was already clear"}
        engine.killswitch.reset(by=by)
        log.warning("KILL_SWITCH_RESET via /api/risk/reset by %s", by)
        return {"status": "reset", "by": by}

    @router.get("/leaderboard")
    async def get_leaderboard(request: Request, regime: Optional[str] = None) -> dict:
        """Return agent leaderboard sorted by ELO.

        Optional ``?regime=normal_vol`` query param to filter by a single market
        regime.  Without the param, mean ELO across all regimes is returned.
        """
        scorer = getattr(request.app.state, "scorer", None)
        if scorer is None:
            raise HTTPException(status_code=503, detail="Scorer not initialised")
        rows = scorer.get_leaderboard(regime=regime)
        return {
            "regime": regime or "all",
            "agents": rows,
        }

    @router.get("/agent/{agent_id}/profile")
    async def get_agent_profile(request: Request, agent_id: str) -> dict:
        """Full agent profile: ELO per regime, win history, accuracy trend."""
        scorer = getattr(request.app.state, "scorer", None)
        if scorer is None:
            raise HTTPException(status_code=503, detail="Scorer not initialised")
        from swarmspx.scoring import KNOWN_AGENTS
        if agent_id not in KNOWN_AGENTS:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
        profile = scorer.get_agent_profile(agent_id)
        return profile

    @router.get("/backtest")
    async def run_backtest(request: Request, signals: int = 500, seed: int = 42) -> dict:
        """Run a Monte-Carlo backtest simulation and return aggregate results.

        Simulates *signals* outcome events with seeded randomness, crediting all
        24 known agents, then returns the leaderboard and summary statistics.
        The live scorer is NOT mutated — a temporary in-memory scorer is used.
        """
        if signals < 1 or signals > 10_000:
            raise HTTPException(status_code=400, detail="signals must be between 1 and 10000")

        from swarmspx.scoring import AgentScorer, KNOWN_AGENTS, KNOWN_REGIMES

        # Build an ephemeral scorer backed by an in-memory DuckDB instance
        try:
            from swarmspx.db import Database
            tmp_db = Database(":memory:")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Could not create temp DB: {exc}")

        tmp_scorer = AgentScorer(tmp_db)

        rng = random.Random(seed)
        regimes = list(KNOWN_REGIMES)
        agents = list(KNOWN_AGENTS)
        outcomes = ["win", "loss"]
        directions = ["BULL", "BEAR", "NEUTRAL"]

        wins = losses = 0
        for i in range(signals):
            regime = rng.choice(regimes)
            consensus_dir = rng.choice(directions[:2])  # BULL or BEAR only
            outcome = rng.choice(outcomes)
            if outcome == "win":
                wins += 1
            else:
                losses += 1

            # Each agent casts a vote with random direction/conviction
            agent_votes = [
                {
                    "agent_id": a,
                    "direction": rng.choice(directions),
                    "conviction": rng.uniform(10, 100),
                }
                for a in agents
            ]
            tmp_scorer.process_signal_outcome(
                signal_id=i,
                outcome=outcome,
                regime=regime,
                agent_votes=agent_votes,
                consensus_direction=consensus_dir,
            )

        leaderboard = tmp_scorer.get_leaderboard()
        top = leaderboard[0] if leaderboard else {}
        bottom = leaderboard[-1] if leaderboard else {}

        return {
            "params": {"signals": signals, "seed": seed},
            "summary": {
                "total_signals": signals,
                "wins": wins,
                "losses": losses,
                "win_rate": round(wins / signals * 100, 1),
            },
            "top_agent": top,
            "bottom_agent": bottom,
            "leaderboard": leaderboard,
        }

    return router
