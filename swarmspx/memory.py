"""AOMS memory client — async, non-blocking, fail-soft.

Why async:
    The engine pipeline runs inside asyncio. Sync httpx.post() inside a
    `pit._run_round()` call serialises 24+ blocking HTTP requests per cycle,
    each up to 5s. That freezes the FastAPI server and WebSocket pushes
    (review #6). Async client keeps the loop alive.

Why fail-soft:
    AOMS at localhost:9100 is OPTIONAL. If it's down, agents still work and
    signals still resolve — we just lose the memory-retrieval / outcome-feedback
    layer. All exceptions are logged (not silently swallowed — review #H5) but
    do NOT propagate to the caller.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class AOMemory:
    """Async interface to AOMS memory service at localhost:9100."""

    def __init__(self, base_url: str = "http://localhost:9100"):
        self.base_url = base_url.rstrip("/")
        self.timeout = httpx.Timeout(5.0, connect=2.0)
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        """Lazily build the AsyncClient (cannot await in __init__)."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self._client

    async def aclose(self) -> None:
        """Close the underlying HTTP client. Safe to call multiple times."""
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                logger.exception("AOMemory aclose failed")
            self._client = None

    # ── Recall ────────────────────────────────────────────────────────────

    async def recall(
        self,
        query: str,
        limit: int = 10,
        min_score: float = 0.6,
    ) -> list[dict]:
        """Retrieve relevant memories for context injection. Returns [] on failure."""
        client = self._get_client()
        try:
            r = await client.post(
                "/recall",
                json={"query": query, "limit": limit, "min_relevance": min_score},
            )
            if r.status_code == 200:
                data = r.json()
                return data.get("results", data.get("entries", []))
            logger.debug("AOMS recall returned %d for query=%r", r.status_code, query)
            return []
        except httpx.TimeoutException:
            logger.warning("AOMS recall timed out for query=%r", query)
            return []
        except Exception:
            logger.exception("AOMS recall failed for query=%r", query)
            return []

    async def recall_for_agent(
        self,
        agent_id: str,
        specialty: str,
        market_context: str,
    ) -> str:
        """Build a memory-prompt string for agent context. Returns '' on failure."""
        query = f"{specialty} SPX trading {market_context}"
        memories = await self.recall(query, limit=5)
        if not memories:
            return ""
        lines = ["Relevant past experiences:"]
        for m in memories[:5]:
            content = m.get("content", m.get("payload", {}).get("content", ""))
            if content:
                lines.append(f"- {str(content)[:200]}")
        return "\n".join(lines)

    # ── Store ─────────────────────────────────────────────────────────────

    async def store_result(
        self,
        direction: str,
        confidence: float,
        trade_setup: dict,
        regime: str,
        agent_votes: Optional[dict] = None,
    ) -> Optional[str]:
        """Persist a simulation signal. Returns memory id or None on failure."""
        client = self._get_client()
        payload = {
            "type": "experience",
            "payload": {
                "title": f"SwarmSPX signal: {direction} at {confidence:.0f}% confidence",
                "content": (
                    f"Regime: {regime}. Direction: {direction}. "
                    f"Confidence: {confidence:.1f}%. Setup: {json.dumps(trade_setup)}"
                ),
                "direction": direction,
                "confidence": confidence,
                "regime": regime,
                "trade_setup": trade_setup,
                "agent_votes": agent_votes or {},
                "timestamp": datetime.now().isoformat(),
                "tags": ["swarmspx", "trading", regime, direction.lower()],
            },
            "weight": 1.2,
        }
        try:
            r = await client.post("/memory/episodic", json=payload)
            if r.status_code == 200:
                return r.json().get("id")
            logger.debug("AOMS store_result returned %d", r.status_code)
            return None
        except httpx.TimeoutException:
            logger.warning("AOMS store_result timed out")
            return None
        except Exception:
            logger.exception("AOMS store_result failed")
            return None

    async def store_outcome(
        self,
        memory_id: str,
        outcome: str,
        outcome_pct: float,
    ) -> None:
        """Update a stored signal with the resolved outcome. Best-effort."""
        client = self._get_client()
        payload = {
            "type": "outcome",
            "payload": {
                "title": f"SwarmSPX outcome: {outcome} ({outcome_pct:+.1f}%)",
                "content": (
                    f"Signal {memory_id} resolved: {outcome} at {outcome_pct:+.1f}%"
                ),
                "related_signal_id": memory_id,
                "outcome": outcome,
                "outcome_pct": outcome_pct,
                "tags": ["swarmspx", "outcome", outcome.lower()],
            },
            "weight": 1.5,
        }
        try:
            await client.post("/memory/episodic", json=payload)
        except httpx.TimeoutException:
            logger.warning("AOMS store_outcome timed out for memory_id=%s", memory_id)
        except Exception:
            logger.exception("AOMS store_outcome failed for memory_id=%s", memory_id)
