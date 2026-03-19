"""Backtesting engine for validating weighted vs equal-weight consensus.

Generates synthetic trading scenarios with known outcomes, runs them
through the scoring system, and compares weighted vs unweighted P&L.
"""

import random
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

# All 24 agent IDs from config/agents.yaml
AGENT_IDS = [
    "vwap_victor", "gamma_gary", "delta_dawn", "momentum_mike", "level_lucy", "tick_tina",
    "fed_fred", "flow_fiona", "vix_vinny", "gex_gina", "putcall_pete", "breadth_brad",
    "twitter_tom", "contrarian_carl", "fear_felicia", "news_nancy", "retail_ray", "whale_wanda",
    "calendar_cal", "spread_sam", "scalp_steve", "swing_sarah", "risk_rick", "synthesis_syd",
]

REGIMES = ["low_vol_grind", "low_vol_trending", "normal_vol", "elevated_vol", "high_vol_panic"]
DIRECTIONS = ["BULL", "BEAR", "NEUTRAL"]


@dataclass
class AgentProfile:
    """Simulated agent with regime-specific accuracy."""
    agent_id: str
    regime_accuracy: dict[str, float] = field(default_factory=dict)

    @classmethod
    def random(cls, agent_id: str) -> "AgentProfile":
        """Create agent with random accuracy per regime (0.3 to 0.8)."""
        return cls(
            agent_id=agent_id,
            regime_accuracy={r: random.uniform(0.3, 0.8) for r in REGIMES},
        )


@dataclass
class SyntheticSignal:
    """A generated trading signal with known correct direction."""
    signal_id: int
    regime: str
    correct_direction: str  # what the market actually did
    agent_votes: list[dict]  # [{agent_id, direction, conviction}]


@dataclass
class BacktestResult:
    """Results from a backtesting run."""
    total_signals: int
    equal_weight_wins: int
    equal_weight_losses: int
    weighted_wins: int
    weighted_losses: int
    equal_win_rate: float
    weighted_win_rate: float
    improvement_pct: float
    agent_leaderboard: list[dict]
    regime_breakdown: dict[str, dict]
    signals_needed_for_convergence: int


class BacktestEngine:
    """Simulate trading scenarios to validate weighted consensus."""

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)
        self.agents: dict[str, AgentProfile] = {}
        self._init_agents()

    def _init_agents(self):
        """Create 24 agents with distinct regime-specific accuracy profiles.

        Some agents are genuinely skilled in certain regimes (accuracy 0.6-0.85),
        average in others (0.45-0.55), and poor in some (0.25-0.40).
        This models real-world specialization.
        """
        for agent_id in AGENT_IDS:
            accuracies = {}
            # Each agent has 1-2 strong regimes, 1-2 weak ones
            strong_regimes = self.rng.sample(REGIMES, k=self.rng.randint(1, 2))
            weak_regimes = self.rng.sample(
                [r for r in REGIMES if r not in strong_regimes],
                k=self.rng.randint(1, 2),
            )
            for regime in REGIMES:
                if regime in strong_regimes:
                    accuracies[regime] = self.rng.uniform(0.60, 0.85)
                elif regime in weak_regimes:
                    accuracies[regime] = self.rng.uniform(0.25, 0.40)
                else:
                    accuracies[regime] = self.rng.uniform(0.42, 0.58)
            self.agents[agent_id] = AgentProfile(agent_id=agent_id, regime_accuracy=accuracies)

    def generate_signal(self, signal_id: int, regime: str) -> SyntheticSignal:
        """Generate a synthetic signal with agent votes based on their accuracy profiles."""
        correct_direction = self.rng.choice(["BULL", "BEAR"])
        votes = []
        for agent_id, profile in self.agents.items():
            accuracy = profile.regime_accuracy.get(regime, 0.5)
            # Agent votes correctly with probability = their accuracy for this regime
            if self.rng.random() < accuracy:
                direction = correct_direction
            else:
                # Wrong vote — could be opposite or neutral
                wrong_dirs = [d for d in DIRECTIONS if d != correct_direction]
                direction = self.rng.choice(wrong_dirs)
            conviction = self.rng.randint(40, 95)
            votes.append({"agent_id": agent_id, "direction": direction, "conviction": conviction})
        return SyntheticSignal(
            signal_id=signal_id,
            regime=regime,
            correct_direction=correct_direction,
            agent_votes=votes,
        )

    def equal_weight_consensus(self, votes: list[dict]) -> str:
        """Simple majority vote (current system)."""
        counts = defaultdict(int)
        for v in votes:
            counts[v["direction"]] += 1
        return max(counts, key=lambda d: counts[d])

    def weighted_consensus(self, votes: list[dict], weights: dict[str, float]) -> str:
        """Performance-weighted vote."""
        weighted_sums = defaultdict(float)
        for v in votes:
            w = weights.get(v["agent_id"], 1.0 / len(votes))
            weighted_sums[v["direction"]] += w
        return max(weighted_sums, key=lambda d: weighted_sums[d])

    def compute_weights(self, elo_scores: dict[str, float]) -> dict[str, float]:
        """Convert ELO scores to normalized weights using softmax with temperature."""
        if not elo_scores:
            n = len(AGENT_IDS)
            return {aid: 1.0 / n for aid in AGENT_IDS}

        temperature = 200.0
        floor = 0.02
        ids = list(elo_scores.keys())
        scores = [elo_scores[aid] for aid in ids]

        # Softmax
        max_score = max(scores)
        exp_scores = [math.exp((s - max_score) / temperature) for s in scores]
        total = sum(exp_scores)
        raw_weights = {aid: exp_scores[i] / total for i, aid in enumerate(ids)}

        # Apply floor
        n = len(ids)
        total_floor = floor * n
        remaining = 1.0 - total_floor
        weights = {}
        for aid in ids:
            weights[aid] = floor + remaining * raw_weights[aid]

        # Renormalize
        w_total = sum(weights.values())
        return {aid: w / w_total for aid, w in weights.items()}

    def update_elo(
        self,
        elo_scores: dict[str, float],
        signal_counts: dict[str, int],
        votes: list[dict],
        correct_direction: str,
        regime: str,
    ) -> None:
        """Update ELO scores for all agents based on signal outcome."""
        avg_elo = sum(elo_scores.values()) / len(elo_scores) if elo_scores else 1000.0

        for v in votes:
            aid = v["agent_id"]
            if aid not in elo_scores:
                elo_scores[aid] = 1000.0
                signal_counts[aid] = 0

            count = signal_counts.get(aid, 0)
            # Adaptive K-factor
            if count < 20:
                k = 40.0
            elif count < 50:
                k = 20.0
            else:
                k = 10.0

            # Expected score (probability of being correct given ELO)
            expected = 1.0 / (1.0 + 10.0 ** ((avg_elo - elo_scores[aid]) / 400.0))

            # Actual: 1.0 if correct, 0.0 if wrong
            actual = 1.0 if v["direction"] == correct_direction else 0.0

            elo_scores[aid] += k * (actual - expected)
            signal_counts[aid] = count + 1

    def run(
        self,
        num_signals: int = 500,
        warmup_signals: int = 30,
        regime_distribution: Optional[dict[str, float]] = None,
    ) -> BacktestResult:
        """Run a full backtest simulation.

        Args:
            num_signals: Total signals to simulate
            warmup_signals: How many signals before weighted consensus starts
                           (let ELO scores develop first)
            regime_distribution: Probability of each regime occurring.
                                Defaults to roughly realistic distribution.
        """
        if regime_distribution is None:
            regime_distribution = {
                "low_vol_grind": 0.30,
                "low_vol_trending": 0.20,
                "normal_vol": 0.25,
                "elevated_vol": 0.15,
                "high_vol_panic": 0.10,
            }

        regimes_list = list(regime_distribution.keys())
        regime_probs = list(regime_distribution.values())

        # Per-regime ELO scores
        regime_elos: dict[str, dict[str, float]] = {r: {} for r in REGIMES}
        regime_counts: dict[str, dict[str, int]] = {r: {} for r in REGIMES}

        equal_wins = 0
        equal_losses = 0
        weighted_wins = 0
        weighted_losses = 0

        regime_stats = {r: {"equal_wins": 0, "equal_total": 0, "weighted_wins": 0, "weighted_total": 0}
                        for r in REGIMES}

        # Track when weighted first outperforms (convergence point)
        rolling_equal = 0
        rolling_weighted = 0
        convergence_signal = num_signals  # default: never converged

        for i in range(num_signals):
            regime = self.rng.choices(regimes_list, weights=regime_probs, k=1)[0]
            signal = self.generate_signal(signal_id=i, regime=regime)

            # Equal weight consensus
            eq_dir = self.equal_weight_consensus(signal.agent_votes)
            eq_correct = eq_dir == signal.correct_direction
            if eq_correct:
                equal_wins += 1
            else:
                equal_losses += 1

            regime_stats[regime]["equal_total"] += 1
            if eq_correct:
                regime_stats[regime]["equal_wins"] += 1

            # Weighted consensus (only after warmup)
            if i >= warmup_signals:
                weights = self.compute_weights(regime_elos.get(regime, {}))
                w_dir = self.weighted_consensus(signal.agent_votes, weights)
            else:
                w_dir = eq_dir  # during warmup, same as equal

            w_correct = w_dir == signal.correct_direction
            if w_correct:
                weighted_wins += 1
            else:
                weighted_losses += 1

            regime_stats[regime]["weighted_total"] += 1
            if w_correct:
                regime_stats[regime]["weighted_wins"] += 1

            # Update ELO scores for this regime
            self.update_elo(
                regime_elos[regime],
                regime_counts.setdefault(regime, {}),
                signal.agent_votes,
                signal.correct_direction,
                regime,
            )

            # Track convergence
            if i >= warmup_signals:
                rolling_equal += int(eq_correct)
                rolling_weighted += int(w_correct)
                if rolling_weighted > rolling_equal and convergence_signal == num_signals:
                    convergence_signal = i

        # Build agent leaderboard (global average ELO across regimes)
        global_elos = defaultdict(list)
        for regime, elos in regime_elos.items():
            for aid, elo in elos.items():
                global_elos[aid].append(elo)

        leaderboard = []
        for aid in AGENT_IDS:
            elos = global_elos.get(aid, [1000.0])
            avg_elo = sum(elos) / len(elos)
            regime_detail = {
                r: round(regime_elos[r].get(aid, 1000.0), 1) for r in REGIMES
            }
            best_regime = max(regime_detail, key=lambda r: regime_detail[r])
            worst_regime = min(regime_detail, key=lambda r: regime_detail[r])
            true_acc = {r: round(self.agents[aid].regime_accuracy[r] * 100, 1) for r in REGIMES}
            leaderboard.append({
                "agent_id": aid,
                "avg_elo": round(avg_elo, 1),
                "best_regime": best_regime,
                "worst_regime": worst_regime,
                "regime_elos": regime_detail,
                "true_accuracy": true_acc,
            })
        leaderboard.sort(key=lambda x: x["avg_elo"], reverse=True)

        # Regime breakdown
        regime_breakdown = {}
        for r in REGIMES:
            s = regime_stats[r]
            eq_wr = (s["equal_wins"] / s["equal_total"] * 100) if s["equal_total"] > 0 else 0
            w_wr = (s["weighted_wins"] / s["weighted_total"] * 100) if s["weighted_total"] > 0 else 0
            regime_breakdown[r] = {
                "signals": s["equal_total"],
                "equal_win_rate": round(eq_wr, 1),
                "weighted_win_rate": round(w_wr, 1),
                "improvement": round(w_wr - eq_wr, 1),
            }

        equal_wr = (equal_wins / num_signals * 100) if num_signals > 0 else 0
        weighted_wr = (weighted_wins / num_signals * 100) if num_signals > 0 else 0

        return BacktestResult(
            total_signals=num_signals,
            equal_weight_wins=equal_wins,
            equal_weight_losses=equal_losses,
            weighted_wins=weighted_wins,
            weighted_losses=weighted_losses,
            equal_win_rate=round(equal_wr, 1),
            weighted_win_rate=round(weighted_wr, 1),
            improvement_pct=round(weighted_wr - equal_wr, 1),
            agent_leaderboard=leaderboard,
            regime_breakdown=regime_breakdown,
            signals_needed_for_convergence=convergence_signal,
        )

    def run_monte_carlo(self, num_trials: int = 100, signals_per_trial: int = 500) -> dict:
        """Run multiple backtests with different random seeds to get statistical confidence."""
        improvements = []
        convergence_points = []

        for trial in range(num_trials):
            self.rng = random.Random(trial * 7919)  # different seed each trial
            self._init_agents()
            result = self.run(num_signals=signals_per_trial, warmup_signals=30)
            improvements.append(result.improvement_pct)
            convergence_points.append(result.signals_needed_for_convergence)

        improvements.sort()
        convergence_points.sort()
        n = len(improvements)

        return {
            "trials": num_trials,
            "signals_per_trial": signals_per_trial,
            "mean_improvement": round(sum(improvements) / n, 2),
            "median_improvement": round(improvements[n // 2], 2),
            "p5_improvement": round(improvements[int(n * 0.05)], 2),
            "p95_improvement": round(improvements[int(n * 0.95)], 2),
            "pct_trials_improved": round(sum(1 for x in improvements if x > 0) / n * 100, 1),
            "mean_convergence_signal": round(sum(convergence_points) / n, 0),
            "median_convergence_signal": convergence_points[n // 2],
        }


def run_backtest_report(num_signals: int = 500, seed: int = 42) -> str:
    """Run a backtest and return a formatted report string."""
    engine = BacktestEngine(seed=seed)
    result = engine.run(num_signals=num_signals)

    lines = [
        "=" * 60,
        "  SWARMSPX DARWINIAN EVOLUTION — BACKTEST REPORT",
        "=" * 60,
        "",
        f"  Signals simulated: {result.total_signals}",
        f"  Warmup period:     30 signals (equal weight during warmup)",
        "",
        "  OVERALL RESULTS",
        "  ─────────────────────────────────────────",
        f"  Equal-weight win rate:    {result.equal_win_rate}%  ({result.equal_weight_wins}W / {result.equal_weight_losses}L)",
        f"  Weighted win rate:        {result.weighted_win_rate}%  ({result.weighted_wins}W / {result.weighted_losses}L)",
        f"  Improvement:              {result.improvement_pct:+.1f}%",
        f"  Convergence at signal:    #{result.signals_needed_for_convergence}",
        "",
        "  REGIME BREAKDOWN",
        "  ─────────────────────────────────────────",
    ]
    for regime, data in result.regime_breakdown.items():
        imp = data["improvement"]
        arrow = "+" if imp > 0 else ""
        lines.append(
            f"  {regime:20s}  EQ={data['equal_win_rate']:5.1f}%  WT={data['weighted_win_rate']:5.1f}%  "
            f"({arrow}{imp:.1f}%)  [{data['signals']} signals]"
        )

    lines += [
        "",
        "  AGENT LEADERBOARD (Top 10)",
        "  ─────────────────────────────────────────",
    ]
    for i, agent in enumerate(result.agent_leaderboard[:10]):
        lines.append(
            f"  #{i+1:2d}  {agent['agent_id']:20s}  ELO={agent['avg_elo']:7.1f}  "
            f"Best={agent['best_regime']:20s}  Worst={agent['worst_regime']}"
        )

    lines += [
        "",
        "  BOTTOM 5 AGENTS",
        "  ─────────────────────────────────────────",
    ]
    for agent in result.agent_leaderboard[-5:]:
        lines.append(
            f"      {agent['agent_id']:20s}  ELO={agent['avg_elo']:7.1f}  "
            f"Best={agent['best_regime']:20s}  Worst={agent['worst_regime']}"
        )

    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)
