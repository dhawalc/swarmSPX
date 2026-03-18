import httpx
import json
from datetime import datetime
from typing import Optional

class AOMemory:
    """Interface to AOMS memory service at localhost:9100."""

    def __init__(self, base_url: str = "http://localhost:9100"):
        self.base_url = base_url
        self.timeout = 5.0

    def recall(self, query: str, limit: int = 10, min_score: float = 0.6) -> list[dict]:
        """Retrieve relevant memories for agent context injection."""
        try:
            response = httpx.post(
                f"{self.base_url}/recall",
                json={"query": query, "limit": limit, "min_relevance": min_score},
                timeout=self.timeout
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("results", data.get("entries", []))
            return []
        except Exception:
            return []

    def recall_for_agent(self, agent_id: str, specialty: str, market_context: str) -> str:
        """Get formatted memory string for injection into agent prompt."""
        query = f"{specialty} SPX trading {market_context}"
        memories = self.recall(query, limit=5)
        if not memories:
            return ""
        lines = ["Relevant past experiences:"]
        for m in memories[:5]:
            content = m.get("content", m.get("payload", {}).get("content", ""))
            if content:
                lines.append(f"- {str(content)[:200]}")
        return "\n".join(lines)

    def store_result(
        self,
        direction: str,
        confidence: float,
        trade_setup: dict,
        regime: str,
        agent_votes: Optional[dict] = None
    ) -> Optional[str]:
        """Store simulation result as episodic memory."""
        try:
            payload = {
                "type": "experience",
                "payload": {
                    "title": f"SwarmSPX signal: {direction} at {confidence:.0f}% confidence",
                    "content": f"Regime: {regime}. Direction: {direction}. Confidence: {confidence:.1f}%. Setup: {json.dumps(trade_setup)}",
                    "direction": direction,
                    "confidence": confidence,
                    "regime": regime,
                    "trade_setup": trade_setup,
                    "agent_votes": agent_votes or {},
                    "timestamp": datetime.now().isoformat(),
                    "tags": ["swarmspx", "trading", regime, direction.lower()]
                },
                "weight": 1.2
            }
            response = httpx.post(
                f"{self.base_url}/memory/episodic",
                json=payload,
                timeout=self.timeout
            )
            if response.status_code == 200:
                return response.json().get("id")
            return None
        except Exception:
            return None

    def store_outcome(self, memory_id: str, outcome: str, outcome_pct: float):
        """Update a stored signal with actual outcome (call after trade resolves)."""
        try:
            httpx.post(
                f"{self.base_url}/memory/episodic",
                json={
                    "type": "outcome",
                    "payload": {
                        "title": f"SwarmSPX outcome: {outcome} ({outcome_pct:+.1f}%)",
                        "content": f"Signal {memory_id} resolved: {outcome} at {outcome_pct:+.1f}%",
                        "related_signal_id": memory_id,
                        "outcome": outcome,
                        "outcome_pct": outcome_pct,
                        "tags": ["swarmspx", "outcome", outcome.lower()]
                    },
                    "weight": 1.5
                },
                timeout=self.timeout
            )
        except Exception:
            pass
