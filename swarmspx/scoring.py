"""Agent scoring — ELO-like performance tracking per market regime.

Each of the 24 trader agents maintains a separate ELO rating for every market
regime it has been observed in. Ratings are used to weight agent votes during
consensus extraction so that historically accurate agents carry more influence.

Darwinian evolution mechanics:
- Agents start at ELO 1000 in every regime.
- After each signal resolves, agents who predicted correctly gain rating points;
  those who were wrong lose points.
- The K-factor (learning rate) is high early on (many points up for grabs) and
  decreases as sample sizes grow (ratings stabilize once we trust them).
- Contrarians who were right against the crowd gain extra credit.
- Vote weights are derived via softmax so no single agent dominates.
- A minimum weight floor (0.02) ensures even low-rated agents contribute.

Schema (agent_elo_scores table):
    agent_id    VARCHAR
    regime      VARCHAR
    elo         DOUBLE
    wins        INTEGER
    losses      INTEGER
    total       INTEGER
    updated_at  TIMESTAMP
    PRIMARY KEY (agent_id, regime)
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime
from typing import Optional

from swarmspx.db import Database

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

DEFAULT_ELO: float = 1000.0
ELO_SCALE: float = 400.0          # standard ELO scale factor
SOFTMAX_TEMP: float = 200.0        # temperature for weight softmax; higher = more uniform
MIN_WEIGHT: float = 0.02           # floor weight per agent
CONTRARIAN_BONUS: float = 1.5      # multiplier on K when the contrarian was right

# K-factor schedule by number of resolved signals for this agent+regime
K_FACTOR_SCHEDULE = [
    (20,  40.0),   # first 20 signals: K=40
    (50,  20.0),   # signals 21-50:   K=20
    (None, 10.0),  # 50+:             K=10
]

KNOWN_REGIMES = frozenset([
    "low_vol_grind",
    "low_vol_trending",
    "normal_vol",
    "elevated_vol",
    "high_vol_panic",
])

KNOWN_AGENTS = frozenset([
    # Technical tribe
    "vwap_victor", "gamma_gary", "delta_dawn", "momentum_mike",
    "level_lucy", "tick_tina",
    # Macro tribe
    "fed_fred", "flow_fiona", "vix_vinny", "gex_gina",
    "putcall_pete", "breadth_brad",
    # Sentiment tribe
    "twitter_tom", "contrarian_carl", "fear_felicia", "news_nancy",
    "retail_ray", "whale_wanda",
    # Strategist tribe
    "calendar_cal", "spread_sam", "scalp_steve", "swing_sarah",
    "risk_rick", "synthesis_syd",
])


# ── Helper dataclass (plain dict in memory) ──────────────────────────────────

def _default_record(agent_id: str, regime: str) -> dict:
    """Return a fresh score record with ELO 1000."""
    return {
        "agent_id": agent_id,
        "regime": regime,
        "elo": DEFAULT_ELO,
        "wins": 0,
        "losses": 0,
        "total": 0,
        "updated_at": datetime.now().isoformat(),
    }


def _k_factor(total_signals: int) -> float:
    """Return the adaptive K-factor based on how many signals this agent has seen."""
    for threshold, k in K_FACTOR_SCHEDULE:
        if threshold is None or total_signals < threshold:
            return k
    return K_FACTOR_SCHEDULE[-1][1]


def _elo_expected(player_elo: float, opponent_elo: float) -> float:
    """Standard ELO expected score formula."""
    return 1.0 / (1.0 + math.pow(10.0, (opponent_elo - player_elo) / ELO_SCALE))


def _softmax_weights(elos: list[float], temperature: float) -> list[float]:
    """Compute softmax probabilities with a given temperature.

    Dividing by temperature before exp() controls concentration:
    - high T → more uniform (weights closer to equal)
    - low T  → winner-takes-all
    """
    scaled = [e / temperature for e in elos]
    max_s = max(scaled)  # numerical stability: subtract max before exp
    exps = [math.exp(s - max_s) for s in scaled]
    total = sum(exps)
    return [e / total for e in exps]


def _apply_floor(weights: list[float], min_weight: float) -> list[float]:
    """Floor each weight at ``min_weight`` and renormalize so the result sums to 1.0.

    Greedy correct algorithm: any weight that would still be below the floor
    after rescaling gets pinned to ``min_weight`` and removed from the active
    pool; remaining "above-floor" weights are scaled to consume
    ``budget = 1 - n_floored * min_weight``.

    The naive approach (``floored = [max(w, mw) for w in weights];
    return [w / sum(floored) for w in floored]``) is wrong: dividing by the
    inflated total pushes just-floored weights *back below* the floor.  The
    iterative-renormalize version of that approach (10 passes, convergence
    check) does not actually converge in realistic ELO spreads — final weights
    sit a hair below the floor.  This function gives the correct one-shot
    result.

    Edge cases:
      * empty input → ``[]``
      * ``n * min_weight >= 1`` → equal weights (floor unsatisfiable as a
        sum-to-1 constraint; degrade gracefully).
      * all-zero or negative active mass → equal share of remaining budget.
    """
    n = len(weights)
    if n == 0:
        return []
    if n * min_weight >= 1.0:
        return [1.0 / n] * n

    out = [float(w) for w in weights]
    floored = [False] * n

    # Bounded by n iterations: each pass either terminates (no violators)
    # or pins exactly one previously-active weight.
    for _ in range(n + 1):
        active_idx = [i for i in range(n) if not floored[i]]
        if not active_idx:
            break

        budget = 1.0 - sum(min_weight for f in floored if f)
        active_sum = sum(out[i] for i in active_idx)

        if active_sum <= 0:
            # No active mass — share budget equally
            per = budget / len(active_idx)
            for i in active_idx:
                out[i] = per
            break

        scale = budget / active_sum
        violators = [
            i for i in active_idx
            if out[i] * scale < min_weight - 1e-12
        ]
        if not violators:
            for i in active_idx:
                out[i] = out[i] * scale
            break

        # Pin the smallest violator. Pinning one-at-a-time is the only
        # correct choice — pinning all violators simultaneously would
        # over-consume the budget.
        i_min = min(violators, key=lambda i: out[i])
        floored[i_min] = True
        out[i_min] = min_weight

    return out


# ── Main class ───────────────────────────────────────────────────────────────

class AgentScorer:
    """Tracks agent performance with ELO-like ratings per market regime.

    In-memory state is loaded from the database at construction time and
    written back after every ``process_signal_outcome`` call.  Individual
    credit/debit operations only mutate memory; callers must invoke
    ``process_signal_outcome`` (which calls ``_sync_to_db``) to persist.
    """

    def __init__(self, db: Database) -> None:
        self.db = db
        self._ensure_schema()
        # In-memory store: {(agent_id, regime): record_dict}
        self._scores: dict[tuple[str, str], dict] = {}
        self._load_from_db()

    # ── Schema bootstrap ─────────────────────────────────────────────────────

    def _ensure_schema(self) -> None:
        """Create the agent_elo_scores table if it doesn't exist."""
        conn = self.db._connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_elo_scores (
                    agent_id   VARCHAR NOT NULL,
                    regime     VARCHAR NOT NULL,
                    elo        DOUBLE  NOT NULL DEFAULT 1000.0,
                    wins       INTEGER NOT NULL DEFAULT 0,
                    losses     INTEGER NOT NULL DEFAULT 0,
                    total      INTEGER NOT NULL DEFAULT 0,
                    updated_at TIMESTAMP,
                    PRIMARY KEY (agent_id, regime)
                )
            """)
        except Exception:
            logger.exception("Failed to create agent_elo_scores table")
        finally:
            self.db._close(conn)

    # ── DB I/O ───────────────────────────────────────────────────────────────

    def _load_from_db(self) -> None:
        """Populate in-memory cache from database rows."""
        conn = self.db._connect()
        try:
            rows = conn.execute("""
                SELECT agent_id, regime, elo, wins, losses, total, updated_at
                FROM agent_elo_scores
            """).fetchall()
        except Exception:
            logger.exception("Failed to load agent scores from DB")
            rows = []
        finally:
            self.db._close(conn)

        for row in rows:
            agent_id, regime, elo, wins, losses, total, updated_at = row
            key = (agent_id, regime)
            self._scores[key] = {
                "agent_id": agent_id,
                "regime": regime,
                "elo": float(elo),
                "wins": int(wins),
                "losses": int(losses),
                "total": int(total),
                "updated_at": str(updated_at) if updated_at else datetime.now().isoformat(),
            }
        logger.debug("Loaded %d agent-regime score records from DB", len(self._scores))

    def _sync_to_db(self) -> None:
        """Upsert all dirty in-memory records to the database.

        DuckDB supports INSERT OR REPLACE when a PRIMARY KEY conflict occurs.
        """
        if not self._scores:
            return
        records = list(self._scores.values())
        conn = self.db._connect()
        try:
            conn.executemany("""
                INSERT INTO agent_elo_scores
                    (agent_id, regime, elo, wins, losses, total, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (agent_id, regime) DO UPDATE SET
                    elo        = excluded.elo,
                    wins       = excluded.wins,
                    losses     = excluded.losses,
                    total      = excluded.total,
                    updated_at = excluded.updated_at
            """, [
                (r["agent_id"], r["regime"], r["elo"],
                 r["wins"], r["losses"], r["total"], r["updated_at"])
                for r in records
            ])
        except Exception:
            logger.exception("Failed to sync agent scores to DB")
        finally:
            self.db._close(conn)

    # ── Record access (lazy init) ─────────────────────────────────────────────

    def _get_record(self, agent_id: str, regime: str) -> dict:
        """Return the score record for (agent_id, regime), creating it if absent."""
        key = (agent_id, regime)
        if key not in self._scores:
            self._scores[key] = _default_record(agent_id, regime)
        return self._scores[key]

    def _average_elo(self, regime: str) -> float:
        """Compute the mean ELO of all known agents in this regime.

        Used as the 'opponent' ELO in expected-score calculations.
        Agents with no data default to DEFAULT_ELO for this purpose.
        """
        elos = []
        for agent_id in KNOWN_AGENTS:
            key = (agent_id, regime)
            rec = self._scores.get(key)
            elos.append(rec["elo"] if rec else DEFAULT_ELO)
        return sum(elos) / len(elos) if elos else DEFAULT_ELO

    # ── Public API ────────────────────────────────────────────────────────────

    def get_weights(self, regime: str) -> dict[str, float]:
        """Return normalized vote weights for all known agents in the given regime.

        Weights are derived from ELO scores via softmax (temperature=200) and
        then floored at MIN_WEIGHT=0.02 before re-normalisation.

        If the regime is unknown or no data exists, every agent gets equal weight.

        Returns:
            dict mapping agent_id → weight (floats that sum to 1.0).
        """
        agent_ids = sorted(KNOWN_AGENTS)  # deterministic ordering

        # Gather ELO scores (default 1000 for agents with no data in this regime)
        elos = []
        for aid in agent_ids:
            key = (aid, regime)
            rec = self._scores.get(key)
            elos.append(rec["elo"] if rec else DEFAULT_ELO)

        # If all ELOs are identical (no differentiation yet), use equal weights
        if len(set(elos)) == 1:
            equal = 1.0 / len(agent_ids)
            return {aid: equal for aid in agent_ids}

        # Softmax over ELO values, then apply MIN_WEIGHT floor with one-shot
        # renormalization (see _apply_floor docstring for why iterating the
        # naive floor+renorm doesn't actually converge).
        raw_weights = _softmax_weights(elos, SOFTMAX_TEMP)
        weights_arr = _apply_floor(raw_weights, MIN_WEIGHT)
        return dict(zip(agent_ids, weights_arr))

    def credit_agent(
        self,
        agent_id: str,
        regime: str,
        was_correct: bool,
        was_contrarian: bool = False,
    ) -> None:
        """Update an agent's ELO score after a signal resolves.

        Args:
            agent_id:       The agent to update.
            regime:         Market regime the signal occurred in.
            was_correct:    True if the agent's direction matched the outcome.
            was_contrarian: True if the agent disagreed with the consensus
                            direction (contrarians who are right get bonus K).
        """
        if agent_id not in KNOWN_AGENTS:
            logger.warning("credit_agent called with unknown agent_id=%r; ignoring", agent_id)
            return
        if regime not in KNOWN_REGIMES:
            logger.warning("credit_agent called with unknown regime=%r; proceeding anyway", regime)

        rec = self._get_record(agent_id, regime)
        avg_elo = self._average_elo(regime)

        # Adaptive K-factor (based on signals seen by this agent in this regime)
        k = _k_factor(rec["total"])

        # Contrarians who were right earn extra credit (punished crowd was wrong)
        if was_contrarian and was_correct:
            k *= CONTRARIAN_BONUS

        # ELO formula
        expected = _elo_expected(rec["elo"], avg_elo)
        actual = 1.0 if was_correct else 0.0
        new_elo = rec["elo"] + k * (actual - expected)

        # Update record (ELO floored at 1 to avoid negatives)
        rec["elo"] = max(1.0, round(new_elo, 2))
        rec["total"] += 1
        if was_correct:
            rec["wins"] += 1
        else:
            rec["losses"] += 1
        rec["updated_at"] = datetime.now().isoformat()

        logger.debug(
            "ELO update: agent=%s regime=%s correct=%s contrarian=%s "
            "elo: %.1f → %.1f (K=%.1f expected=%.3f)",
            agent_id, regime, was_correct, was_contrarian,
            rec["elo"] - k * (actual - expected), rec["elo"], k, expected,
        )

    def process_signal_outcome(
        self,
        signal_id: int,
        outcome: str,
        regime: str,
        agent_votes: list[dict],
        consensus_direction: str,
    ) -> None:
        """Process a fully resolved signal and update all participating agents.

        Args:
            signal_id:           DB id of the simulation_result row (for logging).
            outcome:             'win', 'loss', or 'scratch'.
            regime:              Market regime at time of signal.
            agent_votes:         List of dicts with keys 'agent_id', 'direction',
                                 'conviction'. Each item represents one agent's
                                 vote at the time of the signal.
            consensus_direction: The direction the swarm agreed on (e.g. 'BULL').

        Resolution logic:
            - 'win'    → agents who agreed with consensus_direction were correct.
            - 'loss'   → agents who disagreed with consensus_direction were correct
                         (the contrarians were right).
            - 'scratch' → no one wins or loses; skip all updates.
        """
        if outcome == "scratch":
            logger.info("Signal %d was a scratch; no ELO updates", signal_id)
            return

        if not agent_votes:
            logger.warning("Signal %d has no agent_votes; skipping ELO update", signal_id)
            return

        # On a win, agents who matched consensus were correct.
        # On a loss, agents who opposed consensus were correct.
        correct_direction = consensus_direction if outcome == "win" else self._opposite(consensus_direction)

        neutral_count = 0
        for vote in agent_votes:
            agent_id = vote.get("agent_id")
            direction = vote.get("direction")

            if not agent_id or not direction:
                continue

            # NEUTRAL votes are abstentions — neither rewarded nor punished.
            # Without this guard, NEUTRAL agents are penalised on every
            # resolved signal because correct_direction is always BULL or BEAR
            # (never NEUTRAL) for a non-scratch outcome. Hedgers would get
            # systematically crushed in the leaderboard.
            if direction == "NEUTRAL":
                neutral_count += 1
                continue

            was_correct = (direction == correct_direction)
            # A contrarian is someone who voted against the consensus
            was_contrarian = (direction != consensus_direction)

            self.credit_agent(
                agent_id=agent_id,
                regime=regime,
                was_correct=was_correct,
                was_contrarian=was_contrarian,
            )

        # Persist updated scores to DB
        self._sync_to_db()
        logger.info(
            "Signal %d processed: outcome=%s regime=%s consensus=%s "
            "agents_updated=%d neutrals_skipped=%d",
            signal_id, outcome, regime, consensus_direction,
            len(agent_votes) - neutral_count, neutral_count,
        )

    def get_leaderboard(self, regime: Optional[str] = None) -> list[dict]:
        """Return agents ranked by ELO, optionally filtered to one regime.

        Args:
            regime: If provided, only include rows for this regime.
                    If None, aggregate across all regimes (mean ELO).

        Returns:
            List of dicts, sorted descending by ELO:
            [{agent_id, regime, elo, wins, losses, win_rate, total_signals}]
        """
        if regime is not None:
            rows = [
                rec for (aid, reg), rec in self._scores.items()
                if reg == regime
            ]
            # Include known agents with no data (at default ELO)
            present = {r["agent_id"] for r in rows}
            for aid in KNOWN_AGENTS:
                if aid not in present:
                    rows.append(_default_record(aid, regime))
        else:
            # Aggregate: mean ELO across all regimes where the agent has data
            by_agent: dict[str, list[dict]] = {}
            for (aid, reg), rec in self._scores.items():
                by_agent.setdefault(aid, []).append(rec)

            rows = []
            for aid in KNOWN_AGENTS:
                records = by_agent.get(aid, [])
                if not records:
                    rows.append({
                        "agent_id": aid,
                        "regime": "all",
                        "elo": DEFAULT_ELO,
                        "wins": 0,
                        "losses": 0,
                        "total_signals": 0,
                        "win_rate": 0.0,
                    })
                    continue
                total_signals = sum(r["total"] for r in records)
                wins = sum(r["wins"] for r in records)
                losses = sum(r["losses"] for r in records)
                mean_elo = sum(r["elo"] for r in records) / len(records)
                rows.append({
                    "agent_id": aid,
                    "regime": "all",
                    "elo": round(mean_elo, 2),
                    "wins": wins,
                    "losses": losses,
                    "total_signals": total_signals,
                    "win_rate": round((wins / total_signals * 100) if total_signals else 0.0, 1),
                })

        # Normalise field names for per-regime rows
        result = []
        for r in rows:
            total = r.get("total") or r.get("total_signals", 0)
            wins = r.get("wins", 0)
            losses = r.get("losses", 0)
            result.append({
                "agent_id": r["agent_id"],
                "regime": r.get("regime", regime or "all"),
                "elo": round(r["elo"], 2),
                "wins": wins,
                "losses": losses,
                "win_rate": round((wins / total * 100) if total else 0.0, 1),
                "total_signals": total,
            })

        return sorted(result, key=lambda x: x["elo"], reverse=True)

    def get_agent_profile(self, agent_id: str) -> dict:
        """Return a full cross-regime profile for a single agent.

        Returns:
            {
                agent_id: str,
                regimes: {regime: {elo, wins, losses, win_rate, total_signals}},
                overall_elo: float,          # mean across all regimes with data
                overall_wins: int,
                overall_losses: int,
                overall_win_rate: float,
                overall_total: int,
                best_regime: str | None,     # regime with highest ELO
                worst_regime: str | None,    # regime with lowest ELO
                trend: str,                  # 'improving' | 'declining' | 'stable' | 'no_data'
            }
        """
        if agent_id not in KNOWN_AGENTS:
            logger.warning("get_agent_profile: unknown agent_id=%r", agent_id)

        regime_data: dict[str, dict] = {}
        for regime in KNOWN_REGIMES:
            key = (agent_id, regime)
            rec = self._scores.get(key)
            if rec:
                total = rec["total"]
                wins = rec["wins"]
                regime_data[regime] = {
                    "elo": round(rec["elo"], 2),
                    "wins": wins,
                    "losses": rec["losses"],
                    "win_rate": round((wins / total * 100) if total else 0.0, 1),
                    "total_signals": total,
                }
            else:
                regime_data[regime] = {
                    "elo": DEFAULT_ELO,
                    "wins": 0,
                    "losses": 0,
                    "win_rate": 0.0,
                    "total_signals": 0,
                }

        # Compute aggregates from regimes that actually have data
        active = [v for v in regime_data.values() if v["total_signals"] > 0]

        if active:
            overall_elo = round(sum(v["elo"] for v in active) / len(active), 2)
            overall_wins = sum(v["wins"] for v in active)
            overall_losses = sum(v["losses"] for v in active)
            overall_total = sum(v["total_signals"] for v in active)
            overall_win_rate = round((overall_wins / overall_total * 100) if overall_total else 0.0, 1)

            # Best / worst regime by ELO (only among regimes with actual data)
            active_regimes = [r for r, v in regime_data.items() if v["total_signals"] > 0]
            best_regime = max(active_regimes, key=lambda r: regime_data[r]["elo"]) if active_regimes else None
            worst_regime = min(active_regimes, key=lambda r: regime_data[r]["elo"]) if active_regimes else None

            # Trend: compare ELO to DEFAULT_ELO
            trend = self._compute_trend(agent_id, active)
        else:
            overall_elo = DEFAULT_ELO
            overall_wins = overall_losses = overall_total = 0
            overall_win_rate = 0.0
            best_regime = worst_regime = None
            trend = "no_data"

        return {
            "agent_id": agent_id,
            "regimes": regime_data,
            "overall_elo": overall_elo,
            "overall_wins": overall_wins,
            "overall_losses": overall_losses,
            "overall_win_rate": overall_win_rate,
            "overall_total": overall_total,
            "best_regime": best_regime,
            "worst_regime": worst_regime,
            "trend": trend,
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _opposite(direction: str) -> str:
        """Return the opposite of BULL/BEAR; NEUTRAL stays NEUTRAL."""
        opposites = {"BULL": "BEAR", "BEAR": "BULL", "NEUTRAL": "NEUTRAL"}
        return opposites.get(direction, direction)

    @staticmethod
    def _compute_trend(agent_id: str, active_regime_records: list[dict]) -> str:
        """Classify the agent's performance trajectory.

        Uses average ELO deviation from the default 1000 baseline across
        all active regimes:
          - 'improving' if mean ELO > 1010 (net positive)
          - 'declining' if mean ELO < 990  (net negative)
          - 'stable'    otherwise
        """
        if not active_regime_records:
            return "no_data"
        mean_elo = sum(r["elo"] for r in active_regime_records) / len(active_regime_records)
        if mean_elo > 1010:
            return "improving"
        elif mean_elo < 990:
            return "declining"
        return "stable"
