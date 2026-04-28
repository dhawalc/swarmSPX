"""Tests for swarmspx.backtest.replay — event-driven backtester scaffold."""

from datetime import datetime

import pytest

from swarmspx.backtest.replay import (
    EventReplayer,
    FillRequest,
    HalfSpreadPlusImpactSlippage,
    SimClock,
    TradeRecord,
    compute_metrics,
    generate_walk_forward_windows,
)


# ── SimClock ─────────────────────────────────────────────────────────────────

def test_simclock_starts_at_t0():
    t0 = datetime(2026, 6, 1, 9, 30)
    clock = SimClock(t0)
    assert clock.now == t0


def test_simclock_advances_forward():
    t0 = datetime(2026, 6, 1, 9, 30)
    clock = SimClock(t0)
    clock.advance_to(datetime(2026, 6, 1, 10, 0))
    assert clock.now == datetime(2026, 6, 1, 10, 0)


def test_simclock_rejects_rewind():
    t0 = datetime(2026, 6, 1, 9, 30)
    clock = SimClock(t0)
    clock.advance_to(datetime(2026, 6, 1, 10, 0))
    with pytest.raises(ValueError):
        clock.advance_to(datetime(2026, 6, 1, 9, 45))


# ── EventReplayer (scaffold — fails loudly) ──────────────────────────────────

def test_event_replayer_raises_on_missing_file():
    """Missing parquet must fail loudly, not silently produce fake data."""
    rep = EventReplayer("/nonexistent.parquet")
    with pytest.raises(FileNotFoundError):
        list(rep.stream())


def test_event_replayer_streams_d2dt_spy_when_present():
    """When the D2DT SPY parquet is available, EventReplayer yields events."""
    import os
    from pathlib import Path
    spy_path = Path("/home/dhawal/D2DT/backend/data/minute_cache/SPY_1m_5d.parquet")
    if not spy_path.exists():
        pytest.skip("D2DT data not available in this environment")

    rep = EventReplayer(str(spy_path))
    # Iterate first 5 events to verify schema + multiplier
    events = []
    for i, e in enumerate(rep.stream()):
        events.append(e)
        if i >= 4:
            break

    assert len(events) == 5
    for e in events:
        assert e.event_type == "minute_bar"
        assert e.spx_price > 1000  # SPY × 10 should be ~5000-7000 SPX equivalent
        assert e.spx_bid > 0 and e.spx_ask > 0
        assert e.spx_bid <= e.spx_ask
        assert "volume" in e.payload


# ── HalfSpreadPlusImpactSlippage ─────────────────────────────────────────────

def test_market_buy_pays_half_spread():
    slip = HalfSpreadPlusImpactSlippage()
    book = {"bid": 100.0, "ask": 101.0}
    req = FillRequest(side="BUY", quantity=1, order_type="MKT")
    result = slip.simulate_fill(req, book)
    assert result.filled
    assert result.fill_price == pytest.approx(101.0, rel=1e-6)


def test_market_sell_pays_half_spread():
    slip = HalfSpreadPlusImpactSlippage()
    book = {"bid": 100.0, "ask": 101.0}
    req = FillRequest(side="SELL", quantity=1, order_type="MKT")
    result = slip.simulate_fill(req, book)
    assert result.filled
    assert result.fill_price == pytest.approx(100.0, rel=1e-6)


def test_market_impact_grows_with_size():
    slip = HalfSpreadPlusImpactSlippage(impact_per_lot_bps=2.0)
    book = {"bid": 100.0, "ask": 101.0}
    small = slip.simulate_fill(FillRequest(side="BUY", quantity=1, order_type="MKT"), book)
    big = slip.simulate_fill(FillRequest(side="BUY", quantity=10, order_type="MKT"), book)
    assert big.fill_price > small.fill_price


def test_limit_order_fills_when_crossed():
    slip = HalfSpreadPlusImpactSlippage()
    book = {"bid": 100.0, "ask": 101.0}
    req = FillRequest(side="BUY", quantity=1, order_type="LMT", limit_price=101.5)
    result = slip.simulate_fill(req, book)
    assert result.filled
    assert result.fill_price == 101.5


def test_limit_order_unfilled_when_not_crossed():
    slip = HalfSpreadPlusImpactSlippage()
    book = {"bid": 100.0, "ask": 101.0}
    req = FillRequest(side="BUY", quantity=1, order_type="LMT", limit_price=99.0)
    result = slip.simulate_fill(req, book)
    assert not result.filled


def test_zero_book_returns_unfilled():
    slip = HalfSpreadPlusImpactSlippage()
    book = {"bid": 0.0, "ask": 0.0}
    req = FillRequest(side="BUY", quantity=1, order_type="MKT")
    result = slip.simulate_fill(req, book)
    assert not result.filled


# ── compute_metrics ──────────────────────────────────────────────────────────

def _trade(pnl_pct: float, signal_id: int = 1) -> TradeRecord:
    """Synthetic trade for metric tests."""
    return TradeRecord(
        signal_id=signal_id,
        open_ts=datetime(2026, 1, 1, 9, 30),
        close_ts=datetime(2026, 1, 1, 11, 30),
        direction="BULL",
        entry_premium=5.0,
        exit_premium=5.0 * (1 + pnl_pct / 100),
        contracts=1,
        pnl_usd=5.0 * pnl_pct,
        pnl_pct=pnl_pct,
        slippage_bps=0.5,
        method="option",
    )


def test_metrics_empty_trades():
    r = compute_metrics([])
    assert r.n_trades == 0
    assert r.win_rate == 0.0


def test_metrics_all_winners():
    r = compute_metrics([_trade(50.0, i) for i in range(5)])
    assert r.n_trades == 5
    assert r.n_wins == 5
    assert r.win_rate == 100.0
    assert r.max_drawdown_pct == 0.0


def test_metrics_mixed():
    r = compute_metrics([
        _trade(100.0), _trade(-50.0), _trade(50.0), _trade(-25.0), _trade(75.0),
    ])
    assert r.n_trades == 5
    assert r.n_wins == 3
    assert r.n_losses == 2
    assert r.win_rate == 60.0
    assert r.avg_win_pct == pytest.approx(75.0)
    assert r.avg_loss_pct == pytest.approx(-37.5)


def test_metrics_drawdown_detected():
    # Win, big loss, small recovery
    r = compute_metrics([_trade(50.0), _trade(-100.0), _trade(20.0)])
    assert r.max_drawdown_pct > 0


def test_metrics_sharpe_finite():
    r = compute_metrics([_trade(10.0), _trade(-5.0), _trade(15.0), _trade(-2.0)])
    assert r.sharpe != 0.0
    # Should not be NaN/inf
    assert r.sharpe == r.sharpe  # NaN check
    assert abs(r.sharpe) < 1e6


# ── generate_walk_forward_windows ────────────────────────────────────────────

def test_walk_forward_basic():
    start = datetime(2024, 1, 1)
    end = datetime(2026, 1, 1)
    windows = generate_walk_forward_windows(start, end, train_days=365, test_days=90, step_days=90)
    assert len(windows) > 0
    for w in windows:
        assert w.train_start < w.train_end == w.test_start < w.test_end
        assert (w.train_end - w.train_start).days == 365
        assert (w.test_end - w.test_start).days == 90


def test_walk_forward_does_not_exceed_end():
    start = datetime(2024, 1, 1)
    end = datetime(2025, 6, 1)
    windows = generate_walk_forward_windows(start, end)
    for w in windows:
        assert w.test_end <= end


def test_walk_forward_empty_when_window_too_large():
    start = datetime(2024, 1, 1)
    end = datetime(2024, 6, 1)  # only 5 months
    windows = generate_walk_forward_windows(start, end, train_days=365, test_days=90)
    assert windows == []
