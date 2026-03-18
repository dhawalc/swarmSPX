from collections import Counter
from swarmspx.agents.base import AgentVote
from typing import Optional

class ConsensusExtractor:
    """Extracts actionable signal from 24 agent votes."""

    def extract(self, votes: list[AgentVote], prior_votes: Optional[list[AgentVote]] = None) -> dict:
        if not votes:
            return self._empty_consensus()

        vote_counts = Counter(v.direction for v in votes)
        total = len(votes)
        majority_dir = vote_counts.most_common(1)[0][0]
        majority_count = vote_counts[majority_dir]
        agreement_pct = (majority_count / total) * 100

        # Weighted confidence: weight by conviction
        majority_votes = [v for v in votes if v.direction == majority_dir]
        avg_conviction = sum(v.conviction for v in majority_votes) / len(majority_votes) if majority_votes else 0
        confidence = (agreement_pct * 0.6) + (avg_conviction * 0.4)

        # Strongest cases
        bull_votes = sorted([v for v in votes if v.direction == "BULL"], key=lambda v: v.conviction, reverse=True)
        bear_votes = sorted([v for v in votes if v.direction == "BEAR"], key=lambda v: v.conviction, reverse=True)

        # High-conviction minority (contrarian alert)
        minority_dir = "BEAR" if majority_dir == "BULL" else "BULL"
        minority_votes = [v for v in votes if v.direction == minority_dir]
        contrarian_alert = any(v.conviction >= 80 for v in minority_votes)

        # Herding detection
        herding = self.detect_herding(prior_votes, votes) if prior_votes else False

        # Opinion shifters
        shifters = [v for v in votes if v.changed_from is not None]

        # Trade setup
        trade_setup = self._construct_trade_setup(majority_dir, confidence, votes)

        return {
            "direction": majority_dir,
            "confidence": round(confidence, 1),
            "agreement_pct": round(agreement_pct, 1),
            "vote_counts": dict(vote_counts),
            "strongest_bull": bull_votes[0].reasoning if bull_votes else "",
            "strongest_bull_agent": bull_votes[0].agent_id if bull_votes else "",
            "strongest_bull_conviction": bull_votes[0].conviction if bull_votes else 0,
            "strongest_bear": bear_votes[0].reasoning if bear_votes else "",
            "strongest_bear_agent": bear_votes[0].agent_id if bear_votes else "",
            "strongest_bear_conviction": bear_votes[0].conviction if bear_votes else 0,
            "contrarian_alert": contrarian_alert,
            "contrarian_count": len(minority_votes),
            "herding_detected": herding,
            "opinion_shifters": len(shifters),
            "trade_setup": trade_setup,
            "top_trade_ideas": self._aggregate_trade_ideas(majority_votes[:5]),
        }

    def detect_herding(self, prior_votes: list[AgentVote], current_votes: list[AgentVote]) -> bool:
        """True if too many agents changed their mind in one round (herd behavior)."""
        if not prior_votes or not current_votes:
            return False
        prior_map = {v.agent_id: v.direction for v in prior_votes}
        changed = sum(
            1 for v in current_votes
            if v.agent_id in prior_map and prior_map[v.agent_id] != v.direction
        )
        return changed >= (len(current_votes) * 0.4)  # 40%+ flipped = herding

    def _construct_trade_setup(self, direction: str, confidence: float, votes: list[AgentVote]) -> dict:
        if direction == "NEUTRAL" or confidence < 55:
            return {"direction": "NEUTRAL", "action": "WAIT", "confidence": round(confidence, 1)}
        action = "BUY" if direction == "BULL" else "SELL"
        option_type = "C" if direction == "BULL" else "P"
        # Aggregate trade ideas from agents
        trade_ideas = [v.trade_idea for v in votes if v.direction == direction and v.trade_idea != "WAIT"]
        return {
            "direction": direction,
            "action": action,
            "option_type": option_type,
            "confidence": round(confidence, 1),
            "suggested_ideas": trade_ideas[:3],
        }

    def _aggregate_trade_ideas(self, votes: list[AgentVote]) -> list[str]:
        return [v.trade_idea for v in votes if v.trade_idea and v.trade_idea != "WAIT"]

    def _empty_consensus(self) -> dict:
        return {
            "direction": "NEUTRAL",
            "confidence": 0.0,
            "agreement_pct": 0.0,
            "vote_counts": {},
            "contrarian_alert": False,
            "herding_detected": False,
            "opinion_shifters": 0,
            "trade_setup": {"direction": "NEUTRAL", "action": "WAIT"},
        }
