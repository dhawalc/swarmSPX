from collections import Counter, defaultdict
from swarmspx.agents.base import AgentVote
from typing import Optional

class ConsensusExtractor:
    """Extracts actionable signal from 24 agent votes."""

    def extract(
        self,
        votes: list[AgentVote],
        prior_votes: Optional[list[AgentVote]] = None,
        agent_weights: Optional[dict[str, float]] = None,
    ) -> dict:
        if not votes:
            return self._empty_consensus()

        # --- Raw (equal-weight) vote counts ---
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

        # --- Performance-weighted voting (optional) ---
        weighted_fields = self._compute_weighted_fields(
            votes, majority_dir, agreement_pct, agent_weights
        )

        # Herding: also flag when weighted agreement diverges significantly from raw
        weight_divergence = (
            abs(weighted_fields["weighted_agreement_pct"] - agreement_pct) > 15
            if agent_weights
            else False
        )

        # Trade setup (use weighted direction when weights are provided)
        effective_direction = weighted_fields["weighted_direction"] if agent_weights else majority_dir
        trade_setup = self._construct_trade_setup(effective_direction, confidence, votes)

        result = {
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
            "herding_detected": herding or weight_divergence,
            "weight_divergence": weight_divergence,
            "opinion_shifters": len(shifters),
            "trade_setup": trade_setup,
            "top_trade_ideas": self._aggregate_trade_ideas(majority_votes[:5]),
        }

        # Merge weighted fields (always present; None values when weights not provided)
        result.update(weighted_fields)
        return result

    # ------------------------------------------------------------------
    # Weighted voting helpers
    # ------------------------------------------------------------------

    def _compute_weighted_fields(
        self,
        votes: list[AgentVote],
        raw_majority_dir: str,
        raw_agreement_pct: float,
        agent_weights: Optional[dict[str, float]],
    ) -> dict:
        """
        Compute all performance-weighted fields.

        When agent_weights is None, returns neutral/passthrough values so the
        caller always gets the same set of keys.
        """
        if not agent_weights:
            return {
                "weighted_direction": raw_majority_dir,
                "weighted_agreement_pct": raw_agreement_pct,
                "weight_boost": 0.0,
                "top_weighted_agents": [],
            }

        # Sum weights per direction; unweighted agents default to equal share
        equal_fallback = 1.0 / len(votes) if votes else 0.0
        weighted_sums: dict[str, float] = defaultdict(float)
        for v in votes:
            w = agent_weights.get(v.agent_id, equal_fallback)
            weighted_sums[v.direction] += w

        total_weight = sum(weighted_sums.values()) or 1.0  # guard against zero

        # Winning direction by weight
        weighted_dir = max(weighted_sums, key=lambda d: weighted_sums[d])
        winner_weight = weighted_sums[weighted_dir]

        # Weighted agreement as a percentage of total weight
        weighted_agreement_pct = (winner_weight / total_weight) * 100

        # How much weighting changed conviction vs raw vote counting
        raw_winner_pct = (
            (sum(1 for v in votes if v.direction == weighted_dir) / len(votes)) * 100
            if votes
            else 0.0
        )
        weight_boost = round(weighted_agreement_pct - raw_winner_pct, 1)

        # Top 5 agents by weight within the winning direction
        winning_votes = [v for v in votes if v.direction == weighted_dir]
        top_weighted_agents = sorted(
            winning_votes,
            key=lambda v: agent_weights.get(v.agent_id, equal_fallback),
            reverse=True,
        )[:5]

        return {
            "weighted_direction": weighted_dir,
            "weighted_agreement_pct": round(weighted_agreement_pct, 1),
            "weight_boost": weight_boost,
            "top_weighted_agents": [v.agent_id for v in top_weighted_agents],
        }

    # ------------------------------------------------------------------
    # Existing helpers (unchanged)
    # ------------------------------------------------------------------

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
            "weight_divergence": False,
            "opinion_shifters": 0,
            "trade_setup": {"direction": "NEUTRAL", "action": "WAIT"},
            "weighted_direction": "NEUTRAL",
            "weighted_agreement_pct": 0.0,
            "weight_boost": 0.0,
            "top_weighted_agents": [],
        }
