"""Tests for swarmspx.backtest.runner — honest backtest baselines."""

from pathlib import Path
import pytest

from swarmspx.backtest.runner import (
    FadeMomentumSignal,
    SMACrossSignal,
    SignalDecision,
    always_wait,
    run_simple_backtest,
)
from swarmspx.backtest.replay import MarketEvent
from datetime import datetime


D2DT_SPY_5D = Path("/home/dhawal/D2DT/backend/data/minute_cache/SPY_1m_5d.parquet")


def _evt(price: float) -> MarketEvent:
    ts = datetime(2026, 1, 1)
    return MarketEvent(
        ts_exchange=ts, ts_arrival=ts, event_type="minute_bar",
        spx_price=price, spx_bid=price - 0.5, spx_ask=price + 0.5,
    )


def test_always_wait_signal():
    assert always_wait(_evt(5450)).direction == "NEUTRAL"


def test_sma_cross_warmup():
    sig = SMACrossSignal(fast=2, slow=4)
    # First 3 events: still warming up
    assert sig(_evt(100)).direction == "NEUTRAL"
    assert sig(_evt(101)).direction == "NEUTRAL"
    assert sig(_evt(102)).direction == "NEUTRAL"
    # 4th event triggers full SMA computation; rising → BULL
    out = sig(_evt(110))
    assert out.direction == "BULL"


def test_sma_cross_bear():
    sig = SMACrossSignal(fast=2, slow=4)
    for p in (100, 100, 100, 100):
        sig(_evt(p))
    # Now drop hard
    out = sig(_evt(80))
    assert out.direction == "BEAR"


def test_fade_momentum():
    sig = FadeMomentumSignal(threshold_bps=30.0)
    # Prime
    sig(_evt(100.0))
    # Big up move → BEAR (fade)
    out = sig(_evt(101.0))  # 100 bps up
    assert out.direction == "BEAR"
    # Big down move → BULL (fade)
    out = sig(_evt(99.5))   # ~150 bps down
    assert out.direction == "BULL"


@pytest.mark.skipif(not D2DT_SPY_5D.exists(), reason="D2DT data not present")
def test_runner_null_hypothesis_zero_trades():
    """always_wait → 0 trades, 0 P&L — verifies pipeline isn't generating
    phantom trades."""
    r = run_simple_backtest(str(D2DT_SPY_5D), signal_fn=always_wait)
    assert r.n_trades == 0
    assert r.total_pnl_usd == 0.0


@pytest.mark.skipif(not D2DT_SPY_5D.exists(), reason="D2DT data not present")
def test_runner_sma_produces_finite_metrics():
    r = run_simple_backtest(str(D2DT_SPY_5D), signal_fn=SMACrossSignal(5, 20))
    assert r.n_trades >= 0
    assert r.sharpe == r.sharpe  # not NaN
    assert r.max_drawdown_pct >= 0
