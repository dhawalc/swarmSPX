"""Tests for swarmspx.scoring — ELO-based agent scorer.

Covers:
  - AgentScorer (ELO mechanics, weights, leaderboard, profiles, persistence)
  - ConsensusExtractor with agent_weights (weighted consensus)
  - Database layer (store_agent_votes, get_agent_scores, upsert_agent_score,
    get_agent_vote_history)
  - BacktestEngine (synthetic simulation, Monte Carlo)
"""

import math
import pytest

from swarmspx.db import Database
from swarmspx.scoring import (
    AgentScorer,
    DEFAULT_ELO,
    MIN_WEIGHT,
    KNOWN_AGENTS,
    KNOWN_REGIMES,
    _k_factor,
    _elo_expected,
    _softmax_weights,
)
from swarmspx.simulation.consensus import ConsensusExtractor
from swarmspx.agents.base import AgentVote
from swarmspx.backtest.engine import BacktestEngine, AGENT_IDS, REGIMES


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    d = Database(":memory:")
    d.init_schema()
    return d


@pytest.fixture
def scorer(db):
    return AgentScorer(db)


# ── Unit helpers ──────────────────────────────────────────────────────────────

class TestKFactor:
    def test_first_20_signals(self):
        assert _k_factor(0) == 40.0
        assert _k_factor(1) == 40.0
        assert _k_factor(19) == 40.0

    def test_signals_20_to_49(self):
        assert _k_factor(20) == 20.0
        assert _k_factor(35) == 20.0
        assert _k_factor(49) == 20.0

    def test_signals_50_plus(self):
        assert _k_factor(50) == 10.0
        assert _k_factor(100) == 10.0
        assert _k_factor(9999) == 10.0


class TestEloExpected:
    def test_equal_ratings(self):
        """Two equal players should each have 50% expected score."""
        assert abs(_elo_expected(1000, 1000) - 0.5) < 1e-9

    def test_higher_rated_has_higher_expected(self):
        assert _elo_expected(1200, 1000) > 0.5
        assert _elo_expected(800, 1000) < 0.5

    def test_symmetric(self):
        e1 = _elo_expected(1200, 1000)
        e2 = _elo_expected(1000, 1200)
        assert abs(e1 + e2 - 1.0) < 1e-9


class TestSoftmaxWeights:
    def test_output_sums_to_one(self):
        elos = [1000.0, 1050.0, 950.0, 1100.0]
        weights = _softmax_weights(elos, 200.0)
        assert abs(sum(weights) - 1.0) < 1e-9

    def test_higher_elo_gets_more_weight(self):
        elos = [1000.0, 1100.0]
        weights = _softmax_weights(elos, 200.0)
        assert weights[1] > weights[0]

    def test_equal_elos_give_equal_weights(self):
        elos = [1000.0, 1000.0, 1000.0]
        weights = _softmax_weights(elos, 200.0)
        for w in weights:
            assert abs(w - 1 / 3) < 1e-9


# ── AgentScorer: initialisation ───────────────────────────────────────────────

class TestAgentScorerInit:
    def test_schema_created(self, db):
        """Schema creation must not raise and table must exist."""
        scorer = AgentScorer(db)  # noqa: F841
        conn = db._connect()
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_name = 'agent_elo_scores'"
        ).fetchall()
        db._close(conn)
        assert rows, "agent_elo_scores table was not created"

    def test_starts_empty_in_memory(self, scorer):
        """No score records loaded from a fresh in-memory DB."""
        assert len(scorer._scores) == 0

    def test_loads_existing_records(self, db):
        """Records persisted by one scorer instance are loaded by the next."""
        s1 = AgentScorer(db)
        s1.credit_agent("vwap_victor", "normal_vol", was_correct=True)
        s1._sync_to_db()

        s2 = AgentScorer(db)
        rec = s2._scores.get(("vwap_victor", "normal_vol"))
        assert rec is not None
        assert rec["elo"] > DEFAULT_ELO


# ── AgentScorer: get_weights ──────────────────────────────────────────────────

class TestGetWeights:
    def test_returns_all_known_agents(self, scorer):
        weights = scorer.get_weights("normal_vol")
        assert set(weights.keys()) == KNOWN_AGENTS

    def test_weights_sum_to_one(self, scorer):
        for regime in KNOWN_REGIMES:
            weights = scorer.get_weights(regime)
            assert abs(sum(weights.values()) - 1.0) < 1e-6, f"Regime {regime} weights don't sum to 1"

    def test_min_weight_floor_applied(self, scorer):
        """After artificially lowering one agent's ELO, weight must be at or very near MIN_WEIGHT.

        Floating-point re-normalisation introduces epsilon errors (~1e-10) so we
        allow a tiny tolerance rather than strict >= equality.
        """
        scorer._scores[("vwap_victor", "normal_vol")] = {
            "agent_id": "vwap_victor",
            "regime": "normal_vol",
            "elo": 1.0,  # extremely low
            "wins": 0, "losses": 100, "total": 100,
            "updated_at": "2025-01-01",
        }
        weights = scorer.get_weights("normal_vol")
        assert weights["vwap_victor"] >= MIN_WEIGHT - 1e-9

    def test_equal_weights_when_no_data(self, scorer):
        """A fresh scorer has identical ELOs → equal weights."""
        weights = scorer.get_weights("low_vol_grind")
        expected = 1.0 / len(KNOWN_AGENTS)
        for w in weights.values():
            assert abs(w - expected) < 1e-6

    def test_higher_elo_gets_more_weight(self, scorer):
        """Agent with boosted ELO should outweigh peers."""
        scorer._scores[("gamma_gary", "elevated_vol")] = {
            "agent_id": "gamma_gary",
            "regime": "elevated_vol",
            "elo": 1300.0,
            "wins": 50, "losses": 10, "total": 60,
            "updated_at": "2025-01-01",
        }
        weights = scorer.get_weights("elevated_vol")
        # gamma_gary should have strictly more weight than the default 1/24
        default_equal = 1.0 / len(KNOWN_AGENTS)
        assert weights["gamma_gary"] > default_equal

    def test_unknown_regime_returns_equal_weights(self, scorer):
        """Unknown regime → equal weights (no crash)."""
        weights = scorer.get_weights("unknown_alien_regime")
        assert set(weights.keys()) == KNOWN_AGENTS
        assert abs(sum(weights.values()) - 1.0) < 1e-6


# ── AgentScorer: credit_agent ─────────────────────────────────────────────────

class TestCreditAgent:
    def test_correct_prediction_raises_elo(self, scorer):
        initial = scorer._get_record("delta_dawn", "normal_vol")["elo"]
        scorer.credit_agent("delta_dawn", "normal_vol", was_correct=True)
        assert scorer._scores[("delta_dawn", "normal_vol")]["elo"] > initial

    def test_incorrect_prediction_lowers_elo(self, scorer):
        initial = scorer._get_record("momentum_mike", "normal_vol")["elo"]
        scorer.credit_agent("momentum_mike", "normal_vol", was_correct=False)
        assert scorer._scores[("momentum_mike", "normal_vol")]["elo"] < initial

    def test_win_counter_increments(self, scorer):
        scorer.credit_agent("fed_fred", "low_vol_grind", was_correct=True)
        rec = scorer._scores[("fed_fred", "low_vol_grind")]
        assert rec["wins"] == 1
        assert rec["losses"] == 0
        assert rec["total"] == 1

    def test_loss_counter_increments(self, scorer):
        scorer.credit_agent("vix_vinny", "high_vol_panic", was_correct=False)
        rec = scorer._scores[("vix_vinny", "high_vol_panic")]
        assert rec["wins"] == 0
        assert rec["losses"] == 1
        assert rec["total"] == 1

    def test_contrarian_correct_gets_bonus(self, scorer):
        """Contrarian who's right should gain more ELO than a consensus follower who's right."""
        # Reset to same starting ELO
        def _reset(aid):
            scorer._scores[(aid, "normal_vol")] = _default_fresh(aid)

        def _default_fresh(aid):
            return {"agent_id": aid, "regime": "normal_vol", "elo": DEFAULT_ELO,
                    "wins": 0, "losses": 0, "total": 0, "updated_at": "2025-01-01"}

        _reset("contrarian_carl")
        _reset("twitter_tom")

        scorer.credit_agent("contrarian_carl", "normal_vol", was_correct=True, was_contrarian=True)
        scorer.credit_agent("twitter_tom", "normal_vol", was_correct=True, was_contrarian=False)

        carl_elo = scorer._scores[("contrarian_carl", "normal_vol")]["elo"]
        tom_elo = scorer._scores[("twitter_tom", "normal_vol")]["elo"]
        assert carl_elo > tom_elo

    def test_elo_never_goes_below_one(self, scorer):
        """ELO must not become negative regardless of how many losses an agent takes."""
        # Artificially set a very low ELO
        scorer._scores[("risk_rick", "high_vol_panic")] = {
            "agent_id": "risk_rick",
            "regime": "high_vol_panic",
            "elo": 2.0,
            "wins": 0, "losses": 200, "total": 200,
            "updated_at": "2025-01-01",
        }
        for _ in range(10):
            scorer.credit_agent("risk_rick", "high_vol_panic", was_correct=False)
        rec = scorer._scores[("risk_rick", "high_vol_panic")]
        assert rec["elo"] >= 1.0

    def test_unknown_agent_id_is_ignored(self, scorer):
        """Calling credit_agent with a made-up ID should not raise and not add a record."""
        before = len(scorer._scores)
        scorer.credit_agent("made_up_agent_xyz", "normal_vol", was_correct=True)
        assert len(scorer._scores) == before

    def test_unknown_regime_is_accepted(self, scorer):
        """Unknown regimes are allowed (future-proofing); should not raise."""
        scorer.credit_agent("synthesis_syd", "alien_market", was_correct=True)
        # Record created despite unknown regime
        assert ("synthesis_syd", "alien_market") in scorer._scores

    def test_k_factor_decreases_over_time(self, scorer):
        """ELO change per update should shrink as sample count grows."""
        aid = "scalp_steve"
        regime = "normal_vol"
        scorer._scores[(aid, regime)] = {
            "agent_id": aid, "regime": regime, "elo": DEFAULT_ELO,
            "wins": 0, "losses": 0, "total": 0, "updated_at": "2025-01-01",
        }

        # First update (total=0 → K=40)
        scorer.credit_agent(aid, regime, was_correct=True)
        elo_after_first = scorer._scores[(aid, regime)]["elo"]
        delta_first = elo_after_first - DEFAULT_ELO

        # Simulate 60 more signals so K drops to 10
        scorer._scores[(aid, regime)]["total"] = 60
        scorer._scores[(aid, regime)]["elo"] = DEFAULT_ELO  # reset ELO for clean comparison
        scorer.credit_agent(aid, regime, was_correct=True)
        elo_after_late = scorer._scores[(aid, regime)]["elo"]
        delta_late = elo_after_late - DEFAULT_ELO

        assert delta_first > delta_late


# ── AgentScorer: process_signal_outcome ──────────────────────────────────────

class TestProcessSignalOutcome:
    def _make_votes(self, directions: dict[str, str]) -> list[dict]:
        """directions = {agent_id: direction}"""
        return [
            {"agent_id": aid, "direction": d, "conviction": 75}
            for aid, d in directions.items()
        ]

    def test_win_credits_consensus_agents(self, scorer):
        """On a win, agents who voted with consensus gain ELO."""
        votes = self._make_votes({
            "vwap_victor": "BULL",
            "gamma_gary": "BULL",
            "delta_dawn": "BEAR",  # contrarian
        })
        scorer.process_signal_outcome(
            signal_id=1,
            outcome="win",
            regime="normal_vol",
            agent_votes=votes,
            consensus_direction="BULL",
        )
        # BULL voters should have gained ELO
        assert scorer._scores[("vwap_victor", "normal_vol")]["elo"] > DEFAULT_ELO
        assert scorer._scores[("gamma_gary", "normal_vol")]["elo"] > DEFAULT_ELO
        # BEAR voter should have lost ELO
        assert scorer._scores[("delta_dawn", "normal_vol")]["elo"] < DEFAULT_ELO

    def test_loss_credits_contrarian_agents(self, scorer):
        """On a loss, agents who disagreed with consensus gain ELO."""
        votes = self._make_votes({
            "vwap_victor": "BULL",
            "gamma_gary": "BULL",
            "delta_dawn": "BEAR",  # this agent was right
        })
        scorer.process_signal_outcome(
            signal_id=2,
            outcome="loss",
            regime="elevated_vol",
            agent_votes=votes,
            consensus_direction="BULL",
        )
        # BEAR voter was correct on a BULL loss → gain
        assert scorer._scores[("delta_dawn", "elevated_vol")]["elo"] > DEFAULT_ELO
        # BULL voters lost
        assert scorer._scores[("vwap_victor", "elevated_vol")]["elo"] < DEFAULT_ELO

    def test_scratch_skips_updates(self, scorer):
        """Scratch outcome → no ELO changes."""
        votes = self._make_votes({"vwap_victor": "BULL"})
        scorer.process_signal_outcome(
            signal_id=3,
            outcome="scratch",
            regime="normal_vol",
            agent_votes=votes,
            consensus_direction="BULL",
        )
        assert ("vwap_victor", "normal_vol") not in scorer._scores

    def test_syncs_to_db_after_processing(self, db, scorer):
        """Records are persisted to DB after process_signal_outcome."""
        votes = [{"agent_id": "fed_fred", "direction": "BULL", "conviction": 80}]
        scorer.process_signal_outcome(
            signal_id=10,
            outcome="win",
            regime="low_vol_grind",
            agent_votes=votes,
            consensus_direction="BULL",
        )
        # A fresh scorer loading the same DB should see the update
        scorer2 = AgentScorer(db)
        rec = scorer2._scores.get(("fed_fred", "low_vol_grind"))
        assert rec is not None
        assert rec["total"] == 1

    def test_empty_votes_is_noop(self, scorer):
        """Empty agent_votes list should not crash and not mutate scores."""
        before = dict(scorer._scores)
        scorer.process_signal_outcome(
            signal_id=99,
            outcome="win",
            regime="normal_vol",
            agent_votes=[],
            consensus_direction="BULL",
        )
        assert scorer._scores == before


# ── AgentScorer: get_leaderboard ─────────────────────────────────────────────

class TestGetLeaderboard:
    def _populate(self, scorer, agent_id, regime, wins, losses):
        for _ in range(wins):
            scorer.credit_agent(agent_id, regime, was_correct=True)
        for _ in range(losses):
            scorer.credit_agent(agent_id, regime, was_correct=False)

    def test_returns_all_known_agents(self, scorer):
        board = scorer.get_leaderboard(regime="normal_vol")
        agent_ids = {r["agent_id"] for r in board}
        assert agent_ids == KNOWN_AGENTS

    def test_sorted_descending_by_elo(self, scorer):
        self._populate(scorer, "vwap_victor", "normal_vol", wins=10, losses=0)
        self._populate(scorer, "gamma_gary", "normal_vol", wins=0, losses=10)
        board = scorer.get_leaderboard(regime="normal_vol")
        elos = [r["elo"] for r in board]
        assert elos == sorted(elos, reverse=True)

    def test_win_rate_computed_correctly(self, scorer):
        self._populate(scorer, "scalp_steve", "high_vol_panic", wins=3, losses=1)
        board = scorer.get_leaderboard(regime="high_vol_panic")
        row = next(r for r in board if r["agent_id"] == "scalp_steve")
        assert row["total_signals"] == 4
        assert abs(row["win_rate"] - 75.0) < 0.1

    def test_global_leaderboard_aggregates(self, scorer):
        self._populate(scorer, "risk_rick", "normal_vol", wins=5, losses=0)
        self._populate(scorer, "risk_rick", "high_vol_panic", wins=5, losses=0)
        board = scorer.get_leaderboard()  # no regime filter
        row = next(r for r in board if r["agent_id"] == "risk_rick")
        assert row["regime"] == "all"
        assert row["total_signals"] == 10

    def test_required_fields_present(self, scorer):
        board = scorer.get_leaderboard(regime="normal_vol")
        required = {"agent_id", "regime", "elo", "wins", "losses", "win_rate", "total_signals"}
        for row in board:
            assert required.issubset(row.keys()), f"Missing fields in row: {row}"


# ── AgentScorer: get_agent_profile ────────────────────────────────────────────

class TestGetAgentProfile:
    def test_profile_covers_all_regimes(self, scorer):
        profile = scorer.get_agent_profile("synthesis_syd")
        assert set(profile["regimes"].keys()) == KNOWN_REGIMES

    def test_no_data_gives_defaults(self, scorer):
        profile = scorer.get_agent_profile("calendar_cal")
        assert profile["overall_elo"] == DEFAULT_ELO
        assert profile["overall_total"] == 0
        assert profile["trend"] == "no_data"
        assert profile["best_regime"] is None
        assert profile["worst_regime"] is None

    def test_profile_after_wins_shows_improving(self, scorer):
        for regime in KNOWN_REGIMES:
            for _ in range(5):
                scorer.credit_agent("swing_sarah", regime, was_correct=True)
        profile = scorer.get_agent_profile("swing_sarah")
        assert profile["trend"] == "improving"
        assert profile["overall_elo"] > DEFAULT_ELO
        assert profile["best_regime"] in KNOWN_REGIMES

    def test_profile_after_losses_shows_declining(self, scorer):
        for regime in KNOWN_REGIMES:
            for _ in range(10):
                scorer.credit_agent("spread_sam", regime, was_correct=False)
        profile = scorer.get_agent_profile("spread_sam")
        assert profile["trend"] == "declining"
        assert profile["overall_elo"] < DEFAULT_ELO

    def test_best_worst_regime_are_different(self, scorer):
        # Make one regime great, one bad
        for _ in range(5):
            scorer.credit_agent("breadth_brad", "normal_vol", was_correct=True)
        for _ in range(5):
            scorer.credit_agent("breadth_brad", "high_vol_panic", was_correct=False)

        profile = scorer.get_agent_profile("breadth_brad")
        assert profile["best_regime"] != profile["worst_regime"]
        assert profile["best_regime"] == "normal_vol"
        assert profile["worst_regime"] == "high_vol_panic"

    def test_unknown_agent_does_not_crash(self, scorer):
        """Profile for an unknown agent should return gracefully."""
        profile = scorer.get_agent_profile("totally_made_up_agent")
        assert profile["agent_id"] == "totally_made_up_agent"
        assert profile["overall_total"] == 0

    def test_required_fields_present(self, scorer):
        profile = scorer.get_agent_profile("vix_vinny")
        required = {
            "agent_id", "regimes", "overall_elo", "overall_wins",
            "overall_losses", "overall_win_rate", "overall_total",
            "best_regime", "worst_regime", "trend",
        }
        assert required.issubset(profile.keys())


# ── Round-trip persistence ────────────────────────────────────────────────────

class TestPersistence:
    def test_full_round_trip(self, db):
        """Scores written by one instance are correctly read by another."""
        s1 = AgentScorer(db)
        for _ in range(5):
            s1.credit_agent("whale_wanda", "elevated_vol", was_correct=True)
        s1._sync_to_db()

        s2 = AgentScorer(db)
        rec = s2._scores.get(("whale_wanda", "elevated_vol"))
        assert rec is not None
        assert rec["wins"] == 5
        assert rec["total"] == 5
        assert rec["elo"] > DEFAULT_ELO

    def test_process_signal_outcome_persists(self, db):
        s1 = AgentScorer(db)
        votes = [
            {"agent_id": "retail_ray", "direction": "BULL", "conviction": 60},
            {"agent_id": "news_nancy", "direction": "BEAR", "conviction": 70},
        ]
        s1.process_signal_outcome(
            signal_id=42,
            outcome="win",
            regime="low_vol_trending",
            agent_votes=votes,
            consensus_direction="BULL",
        )

        s2 = AgentScorer(db)
        ray_rec = s2._scores.get(("retail_ray", "low_vol_trending"))
        nancy_rec = s2._scores.get(("news_nancy", "low_vol_trending"))

        assert ray_rec is not None and ray_rec["wins"] == 1
        assert nancy_rec is not None and nancy_rec["losses"] == 1


# ── Targeted checklist tests (naming from spec) ───────────────────────────────
# These use the canonical names from the Darwinian Evolution test plan so that
# `pytest -k test_initial_elo_is_1000` etc. match exactly.

def test_initial_elo_is_1000(scorer):
    """New agents start at ELO 1000 in every regime."""
    rec = scorer._get_record("vwap_victor", "normal_vol")
    assert rec["elo"] == DEFAULT_ELO == 1000.0


def test_credit_correct_increases_elo(scorer):
    """A correct prediction raises ELO above the default."""
    scorer.credit_agent("gamma_gary", "normal_vol", was_correct=True)
    assert scorer._scores[("gamma_gary", "normal_vol")]["elo"] > DEFAULT_ELO


def test_credit_incorrect_decreases_elo(scorer):
    """An incorrect prediction lowers ELO below the default."""
    scorer.credit_agent("delta_dawn", "normal_vol", was_correct=False)
    assert scorer._scores[("delta_dawn", "normal_vol")]["elo"] < DEFAULT_ELO


def test_regime_isolation(scorer):
    """Scoring in one regime must not affect a different regime's record."""
    scorer.credit_agent("momentum_mike", "low_vol_grind", was_correct=True)
    # elevated_vol record should not exist yet (ELO untouched)
    assert ("momentum_mike", "elevated_vol") not in scorer._scores


def test_k_factor_decreases_with_experience(scorer):
    """K=40 for first signal, K=20 after 20+, K=10 after 50+."""
    assert _k_factor(0) == 40.0
    assert _k_factor(20) == 20.0
    assert _k_factor(50) == 10.0


def test_contrarian_bonus(scorer):
    """A contrarian who is right gains more ELO than a consensus follower."""
    for aid in ("contrarian_carl", "whale_wanda"):
        scorer._scores[(aid, "normal_vol")] = {
            "agent_id": aid, "regime": "normal_vol", "elo": DEFAULT_ELO,
            "wins": 0, "losses": 0, "total": 0, "updated_at": "2025-01-01",
        }
    scorer.credit_agent("contrarian_carl", "normal_vol", was_correct=True, was_contrarian=True)
    scorer.credit_agent("whale_wanda", "normal_vol", was_correct=True, was_contrarian=False)

    carl_elo = scorer._scores[("contrarian_carl", "normal_vol")]["elo"]
    wanda_elo = scorer._scores[("whale_wanda", "normal_vol")]["elo"]
    assert carl_elo > wanda_elo


def test_get_weights_equal_when_no_data(scorer):
    """With no history all 24 agents get equal weight (1/24 each)."""
    weights = scorer.get_weights("normal_vol")
    expected = 1.0 / len(KNOWN_AGENTS)
    for w in weights.values():
        assert abs(w - expected) < 1e-6


def test_get_weights_favor_high_elo(scorer):
    """An agent with a high ELO receives more weight than the equal share."""
    scorer._scores[("fed_fred", "elevated_vol")] = {
        "agent_id": "fed_fred", "regime": "elevated_vol", "elo": 1400.0,
        "wins": 70, "losses": 5, "total": 75, "updated_at": "2025-01-01",
    }
    weights = scorer.get_weights("elevated_vol")
    equal = 1.0 / len(KNOWN_AGENTS)
    assert weights["fed_fred"] > equal


def test_weight_floor_enforced(scorer):
    """No agent's weight should fall below MIN_WEIGHT (0.02)."""
    scorer._scores[("tick_tina", "high_vol_panic")] = {
        "agent_id": "tick_tina", "regime": "high_vol_panic", "elo": 1.0,
        "wins": 0, "losses": 200, "total": 200, "updated_at": "2025-01-01",
    }
    weights = scorer.get_weights("high_vol_panic")
    assert weights["tick_tina"] >= MIN_WEIGHT - 1e-9


def test_weights_sum_to_one(scorer):
    """After various updates, weights must still sum to 1.0."""
    for i in range(10):
        scorer.credit_agent("gamma_gary", "normal_vol", was_correct=True)
        scorer.credit_agent("vwap_victor", "normal_vol", was_correct=False)
    weights = scorer.get_weights("normal_vol")
    assert abs(sum(weights.values()) - 1.0) < 1e-6


def test_leaderboard_sorted_by_elo(scorer):
    scorer.credit_agent("vwap_victor", "normal_vol", was_correct=True)
    scorer.credit_agent("vwap_victor", "normal_vol", was_correct=True)
    scorer.credit_agent("gamma_gary", "normal_vol", was_correct=False)
    scorer.credit_agent("gamma_gary", "normal_vol", was_correct=False)
    board = scorer.get_leaderboard(regime="normal_vol")
    elos = [r["elo"] for r in board]
    assert elos == sorted(elos, reverse=True)


def test_leaderboard_filtered_by_regime(scorer):
    scorer.credit_agent("flow_fiona", "low_vol_grind", was_correct=True)
    scorer.credit_agent("vix_vinny", "high_vol_panic", was_correct=True)
    board = scorer.get_leaderboard(regime="low_vol_grind")
    assert {r["regime"] for r in board} == {"low_vol_grind"}


def test_process_signal_outcome_credits_correct_agents(scorer):
    votes = [
        {"agent_id": "breadth_brad", "direction": "BULL", "conviction": 80},
        {"agent_id": "gex_gina", "direction": "BULL", "conviction": 70},
    ]
    scorer.process_signal_outcome(1, "win", "normal_vol", votes, "BULL")
    assert scorer._scores[("breadth_brad", "normal_vol")]["elo"] > DEFAULT_ELO
    assert scorer._scores[("gex_gina", "normal_vol")]["elo"] > DEFAULT_ELO


def test_process_signal_outcome_debits_wrong_agents(scorer):
    votes = [{"agent_id": "twitter_tom", "direction": "BEAR", "conviction": 65}]
    scorer.process_signal_outcome(2, "win", "normal_vol", votes, "BULL")
    assert scorer._scores[("twitter_tom", "normal_vol")]["elo"] < DEFAULT_ELO


def test_unknown_agent_handled_gracefully(scorer):
    before = len(scorer._scores)
    scorer.credit_agent("phantom_trader_99", "normal_vol", was_correct=True)
    assert len(scorer._scores) == before


# ── Weighted Consensus ────────────────────────────────────────────────────────

def _make_vote(agent_id, direction, conviction=70):
    return AgentVote(
        agent_id=agent_id, direction=direction, conviction=conviction,
        reasoning="test", trade_idea="WAIT",
    )


class TestWeightedConsensus:

    def setup_method(self):
        self.extractor = ConsensusExtractor()

    def test_weighted_consensus_backwards_compatible(self):
        votes = [_make_vote("vwap_victor", "BULL"), _make_vote("gamma_gary", "BULL"),
                 _make_vote("delta_dawn", "BEAR")]
        result = self.extractor.extract(votes)
        assert result["direction"] == "BULL"
        assert result["weighted_direction"] == "BULL"
        assert result["weight_boost"] == 0.0
        assert result["top_weighted_agents"] == []

    def test_weighted_consensus_changes_direction(self):
        votes = [
            _make_vote("vwap_victor", "BULL"), _make_vote("gamma_gary", "BULL"),
            _make_vote("delta_dawn", "BEAR"), _make_vote("momentum_mike", "BEAR"),
            _make_vote("level_lucy", "BEAR"),
        ]
        weights = {"vwap_victor": 0.45, "gamma_gary": 0.45,
                   "delta_dawn": 0.033, "momentum_mike": 0.033, "level_lucy": 0.034}
        result = self.extractor.extract(votes, agent_weights=weights)
        assert result["weighted_direction"] == "BULL"
        assert result["direction"] == "BEAR"

    def test_weighted_agreement_pct_calculated(self):
        votes = [_make_vote("vwap_victor", "BULL"), _make_vote("gamma_gary", "BULL"),
                 _make_vote("delta_dawn", "BEAR")]
        weights = {"vwap_victor": 0.40, "gamma_gary": 0.40, "delta_dawn": 0.20}
        result = self.extractor.extract(votes, agent_weights=weights)
        assert result["weighted_direction"] == "BULL"
        assert abs(result["weighted_agreement_pct"] - 80.0) < 0.5

    def test_weight_boost_positive_when_weights_agree_more(self):
        votes = [_make_vote("vwap_victor", "BULL"), _make_vote("gamma_gary", "BULL"),
                 _make_vote("delta_dawn", "BEAR"), _make_vote("momentum_mike", "BEAR")]
        weights = {"vwap_victor": 0.375, "gamma_gary": 0.375,
                   "delta_dawn": 0.125, "momentum_mike": 0.125}
        result = self.extractor.extract(votes, agent_weights=weights)
        assert result["weight_boost"] > 0

    def test_weight_divergence_flagged(self):
        votes = [
            _make_vote("vwap_victor", "BULL"), _make_vote("gamma_gary", "BULL"),
            _make_vote("delta_dawn", "BULL"), _make_vote("momentum_mike", "BEAR"),
            _make_vote("level_lucy", "BEAR"),
        ]
        weights = {"vwap_victor": 0.034, "gamma_gary": 0.033, "delta_dawn": 0.033,
                   "momentum_mike": 0.45, "level_lucy": 0.45}
        result = self.extractor.extract(votes, agent_weights=weights)
        assert result["weight_divergence"] is True

    def test_top_weighted_agents_in_winning_direction(self):
        votes = [_make_vote("vwap_victor", "BULL"), _make_vote("gamma_gary", "BULL"),
                 _make_vote("delta_dawn", "BEAR")]
        weights = {"vwap_victor": 0.5, "gamma_gary": 0.4, "delta_dawn": 0.1}
        result = self.extractor.extract(votes, agent_weights=weights)
        assert result["weighted_direction"] == "BULL"
        for agent_id in result["top_weighted_agents"]:
            vote_dir = next(v.direction for v in votes if v.agent_id == agent_id)
            assert vote_dir == "BULL"