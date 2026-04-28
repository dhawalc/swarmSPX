"""Tests for swarmspx.risk — pre-trade gate, Kelly sizer, kill switch."""

from datetime import timedelta

import pytest

from swarmspx.clock import now_et
from swarmspx.db import Database
from swarmspx.risk.gate import PreTradeRiskGate
from swarmspx.risk.killswitch import KillSwitch
from swarmspx.risk.sizer import KellyPositionSizer


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    """Ephemeral in-memory DuckDB."""
    d = Database(":memory:")
    d.init_schema()
    return d


@pytest.fixture
def fresh_market_context():
    """Snapshot dict with a recent (live) timestamp."""
    return {
        "timestamp": now_et().isoformat(),
        "spx_price": 5450.0,
        "vix_level": 14.0,
        "market_regime": "normal_vol",
    }


# ── PreTradeRiskGate ─────────────────────────────────────────────────────────

class TestRiskGate:

    def test_neutral_signal_rejected(self, db, fresh_market_context):
        gate = PreTradeRiskGate(db)
        card = {"direction": "NEUTRAL", "strategy_type": "WAIT"}
        decision = gate.check(card, fresh_market_context)
        assert decision.action == "REJECT"
        assert "non_directional" in decision.reasons

    def test_kill_switch_short_circuits(self, db, fresh_market_context):
        gate = PreTradeRiskGate(db)
        card = {"direction": "BULL", "strategy_type": "STRAIGHT", "strike": 5450, "option_type": "call"}
        decision = gate.check(card, fresh_market_context, kill_switch_active=True)
        assert decision.action == "REJECT"
        assert decision.reasons == ["kill_switch_active"]

    def test_pass_on_clean_state(self, db, fresh_market_context):
        gate = PreTradeRiskGate(db)
        card = {"direction": "BULL", "strategy_type": "STRAIGHT", "strike": 5450, "option_type": "call"}
        decision = gate.check(card, fresh_market_context)
        assert decision.action == "PASS"
        assert decision.reasons == []

    def test_stale_data_rejected(self, db):
        gate = PreTradeRiskGate(db, data_staleness_sec=10)
        card = {"direction": "BULL", "strategy_type": "STRAIGHT", "strike": 5450, "option_type": "call"}
        old_ctx = {
            "timestamp": (now_et() - timedelta(minutes=5)).isoformat(),
            "spx_price": 5450.0,
        }
        decision = gate.check(card, old_ctx)
        assert decision.action == "REJECT"
        assert "stale_market_data" in decision.reasons

    def test_idempotency_blocks_duplicates_within_window(self, db, fresh_market_context):
        gate = PreTradeRiskGate(db)
        card = {"direction": "BULL", "strategy_type": "STRAIGHT", "strike": 5450, "option_type": "call"}
        first = gate.check(card, fresh_market_context)
        assert first.passed
        # Same trade card + same minute bucket → duplicate
        second = gate.check(card, fresh_market_context)
        assert second.action == "REJECT"
        assert "duplicate_order" in second.reasons

    def test_different_strikes_get_different_ids(self, db, fresh_market_context):
        gate = PreTradeRiskGate(db)
        c1 = {"direction": "BULL", "strategy_type": "STRAIGHT", "strike": 5450, "option_type": "call"}
        c2 = {"direction": "BULL", "strategy_type": "STRAIGHT", "strike": 5500, "option_type": "call"}
        d1 = gate.check(c1, fresh_market_context)
        d2 = gate.check(c2, fresh_market_context)
        assert d1.passed and d2.passed
        assert d1.meta["client_order_id"] != d2.meta["client_order_id"]


# ── KellyPositionSizer ───────────────────────────────────────────────────────

class TestKellySizer:

    def test_low_confidence_rejects(self, tmp_path):
        sizer = KellyPositionSizer(lock_dir=str(tmp_path))
        d = sizer.size_for_signal(entry_premium=5.50, confidence=50.0)
        assert d.contracts == 0
        assert d.reason == "low_confidence"

    def test_no_premium_rejects(self, tmp_path):
        sizer = KellyPositionSizer(lock_dir=str(tmp_path))
        d = sizer.size_for_signal(entry_premium=0.0, confidence=80.0)
        assert d.contracts == 0
        assert d.reason == "no_premium"

    def test_normal_size_for_high_confidence(self, tmp_path):
        # Use half-Kelly (0.5) + decent edge so the math produces ≥1 contract
        # on a $5 premium / $25k bankroll. With 0.10 fractional Kelly the
        # default edge gives max_per_trade ≈ $83, below the $500/contract cost.
        sizer = KellyPositionSizer(
            bankroll_usd=25_000,
            kelly_fraction=0.5,
            win_prob=0.65,
            payoff_ratio=3.0,
            lock_dir=str(tmp_path),
        )
        d = sizer.size_for_signal(entry_premium=5.0, confidence=75.0)
        assert d.contracts >= 1
        assert d.risk_usd > 0
        assert d.reason == "normal"

    def test_below_min_size_when_premium_too_large(self, tmp_path):
        sizer = KellyPositionSizer(
            bankroll_usd=1_000,
            kelly_fraction=0.10,
            win_prob=0.55,
            payoff_ratio=3.0,
            lock_dir=str(tmp_path),
        )
        # Per-contract = $5000 ($50 premium × 100); bankroll only $1k
        d = sizer.size_for_signal(entry_premium=50.0, confidence=80.0)
        assert d.contracts == 0
        assert d.reason == "below_min_size"

    def test_lock_file_persists(self, tmp_path):
        sizer = KellyPositionSizer(lock_dir=str(tmp_path))
        cap1 = sizer.get_today_cap()
        # Mutate sizer's bankroll — should NOT affect today's cap
        sizer.bankroll = 99_999_999
        cap2 = sizer.get_today_cap()
        assert cap1["bankroll"] == cap2["bankroll"]
        assert cap1["max_per_trade_usd"] == cap2["max_per_trade_usd"]

    def test_max_per_trade_pct_hard_cap(self, tmp_path):
        # win_prob=0.99 implies near-full Kelly; max_per_trade_pct=0.02 should clamp
        sizer = KellyPositionSizer(
            bankroll_usd=10_000,
            kelly_fraction=1.0,
            win_prob=0.99,
            payoff_ratio=2.0,
            max_per_trade_pct=0.02,
            lock_dir=str(tmp_path),
        )
        cap = sizer.get_today_cap()
        assert cap["max_per_trade_usd"] <= 10_000 * 0.02


# ── KillSwitch ───────────────────────────────────────────────────────────────

class TestKillSwitch:

    def test_default_state_not_tripped(self, tmp_path):
        ks = KillSwitch(state_path=str(tmp_path / "ks.json"))
        assert ks.is_tripped() is False

    def test_manual_trip_persists(self, tmp_path):
        path = str(tmp_path / "ks.json")
        ks = KillSwitch(state_path=path)
        ks.trip("manual", "user requested via telegram")
        assert ks.is_tripped()

        # Fresh instance reads same state from disk
        ks2 = KillSwitch(state_path=path)
        assert ks2.is_tripped()
        assert ks2.state["triggered_by"] == "manual"

    def test_manual_reset_clears(self, tmp_path):
        ks = KillSwitch(state_path=str(tmp_path / "ks.json"))
        ks.trip("manual", "test")
        assert ks.is_tripped()
        ks.reset(by="user")
        assert ks.is_tripped() is False

    def test_daily_loss_band_trips(self, tmp_path):
        ks = KillSwitch(
            state_path=str(tmp_path / "ks.json"),
            daily_loss_pct=3.0,
        )
        ks.evaluate_loss_bands(daily_pnl_pct=-3.5, weekly_pnl_pct=0.0, monthly_pnl_pct=0.0)
        assert ks.is_tripped()
        assert ks.state["triggered_by"] == "daily_loss"

    def test_consecutive_loss_trips(self, tmp_path):
        ks = KillSwitch(state_path=str(tmp_path / "ks.json"), max_consecutive_losses=3)
        ks.evaluate_consecutive_losses(count=3)
        assert ks.is_tripped()
        assert ks.state["triggered_by"] == "consecutive_losses"

    def test_weekly_loss_requires_manual_clear(self, tmp_path):
        ks = KillSwitch(state_path=str(tmp_path / "ks.json"), weekly_loss_pct=6.0)
        ks.evaluate_loss_bands(daily_pnl_pct=0, weekly_pnl_pct=-6.5, monthly_pnl_pct=0)
        assert ks.is_tripped()
        assert ks.state["auto_clear_at"] is None  # manual-clear-only

    def test_data_quality_auto_clears(self, tmp_path):
        ks = KillSwitch(state_path=str(tmp_path / "ks.json"))
        ks.trip("data_quality", "feed stale")
        assert ks.is_tripped()
        assert ks.state["auto_clear_at"] is not None

    def test_unknown_trigger_coerced_to_manual(self, tmp_path):
        ks = KillSwitch(state_path=str(tmp_path / "ks.json"))
        ks.trip("garbage", "unknown reason")
        assert ks.is_tripped()
        assert ks.state["triggered_by"] == "manual"

    def test_corrupt_state_file_fails_safe_to_tripped(self, tmp_path):
        path = tmp_path / "ks.json"
        path.write_text("{not valid json")
        ks = KillSwitch(state_path=str(path))
        assert ks.is_tripped() is True
        assert ks.state["triggered_by"] == "data_quality"
