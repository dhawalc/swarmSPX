"""Tests for swarmspx.paper — shadow trading simulator."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from swarmspx.db import Database
from swarmspx.paper import (
    DEFAULT_STOP_MULTIPLIER,
    DEFAULT_TARGET_MULTIPLIER,
    PaperBroker,
)


@pytest.fixture
def db():
    d = Database(":memory:")
    d.init_schema()
    return d


@pytest.fixture
def broker(db):
    return PaperBroker(db)


def test_open_position_assigns_defaults(broker):
    pid = broker.open_position(
        signal_id=1,
        direction="BULL",
        option_strike=5450.0,
        option_type="call",
        entry_premium=5.50,
        contracts=2,
    )
    assert pid is not None
    [pos] = broker.get_open_positions()
    assert pos.entry_premium == 5.50
    assert pos.contracts == 2
    assert pos.target_premium == pytest.approx(5.50 * DEFAULT_TARGET_MULTIPLIER)
    assert pos.stop_premium == pytest.approx(5.50 * DEFAULT_STOP_MULTIPLIER)
    assert pos.status == "open"


def test_open_position_rejects_bad_inputs(broker):
    assert broker.open_position(
        signal_id=1, direction="BULL", option_strike=5450.0,
        option_type="call", entry_premium=0, contracts=2,
    ) is None
    assert broker.open_position(
        signal_id=1, direction="BULL", option_strike=5450.0,
        option_type="call", entry_premium=5.0, contracts=0,
    ) is None
    assert broker.open_position(
        signal_id=1, direction="BULL", option_strike=5450.0,
        option_type="garbage", entry_premium=5.0, contracts=2,
    ) is None


def test_close_position_won(broker):
    pid = broker.open_position(
        signal_id=1, direction="BULL", option_strike=5450.0,
        option_type="call", entry_premium=5.0, contracts=1,
    )
    ok = broker.close_position(pid, exit_premium=10.0, reason="target_hit")
    assert ok is True
    assert broker.get_open_positions() == []
    summary = broker.get_pnl_summary()
    assert summary["won"] == 1
    assert summary["pnl_usd"] == pytest.approx(500.0)  # ($10 - $5) * 1 * 100


def test_close_position_lost(broker):
    pid = broker.open_position(
        signal_id=1, direction="BULL", option_strike=5450.0,
        option_type="call", entry_premium=5.0, contracts=1,
    )
    broker.close_position(pid, exit_premium=2.5, reason="stop_hit")
    summary = broker.get_pnl_summary()
    assert summary["lost"] == 1
    assert summary["pnl_usd"] == pytest.approx(-250.0)


def test_close_position_expired(broker):
    pid = broker.open_position(
        signal_id=1, direction="BULL", option_strike=5450.0,
        option_type="call", entry_premium=5.0, contracts=1,
    )
    broker.close_position(pid, exit_premium=0.0, reason="eod_worthless")
    summary = broker.get_pnl_summary()
    assert summary["expired"] == 1


def test_close_position_idempotent_on_already_closed(broker):
    pid = broker.open_position(
        signal_id=1, direction="BULL", option_strike=5450.0,
        option_type="call", entry_premium=5.0, contracts=1,
    )
    assert broker.close_position(pid, exit_premium=10.0, reason="r1") is True
    # Second close should fail (no-op)
    assert broker.close_position(pid, exit_premium=15.0, reason="r2") is False


def test_check_exits_closes_on_target(broker):
    broker.open_position(
        signal_id=1, direction="BULL", option_strike=5450.0,
        option_type="call", entry_premium=5.0, contracts=1,
    )
    fetcher = type("F", (), {})()
    fetcher.lookup_option_premium = AsyncMock(return_value=12.0)
    events = asyncio.run(broker.check_exits(fetcher))
    assert len(events) == 1
    assert events[0]["status"] == "won"
    assert events[0]["exit_premium"] == 12.0
    assert "target_hit" in events[0]["reason"]


def test_check_exits_closes_on_stop(broker):
    broker.open_position(
        signal_id=1, direction="BULL", option_strike=5450.0,
        option_type="call", entry_premium=5.0, contracts=1,
    )
    fetcher = type("F", (), {})()
    fetcher.lookup_option_premium = AsyncMock(return_value=2.0)
    events = asyncio.run(broker.check_exits(fetcher))
    assert len(events) == 1
    assert events[0]["status"] == "lost"
    assert "stop_hit" in events[0]["reason"]


def test_check_exits_skips_when_no_chain_during_session(broker, monkeypatch):
    """During market hours with no chain → defer (don't close).

    paper.check_exits imports is_after_hours from swarmspx.clock at call
    time, so the patch must target the source module, not paper.
    """
    monkeypatch.setattr("swarmspx.clock.is_after_hours", lambda dt=None: False)
    broker.open_position(
        signal_id=1, direction="BULL", option_strike=5450.0,
        option_type="call", entry_premium=5.0, contracts=1,
    )
    fetcher = type("F", (), {})()
    fetcher.lookup_option_premium = AsyncMock(return_value=None)
    events = asyncio.run(broker.check_exits(fetcher))
    assert events == []
    assert len(broker.get_open_positions()) == 1


def test_pnl_summary_aggregates(broker):
    # 2 wins, 1 loss, 1 expired, 1 still open
    p1 = broker.open_position(signal_id=1, direction="BULL", option_strike=5450,
                              option_type="call", entry_premium=5.0, contracts=1)
    broker.close_position(p1, 10.0, "target")          # +$500
    p2 = broker.open_position(signal_id=2, direction="BULL", option_strike=5450,
                              option_type="call", entry_premium=5.0, contracts=2)
    broker.close_position(p2, 8.0, "target")           # +$600
    p3 = broker.open_position(signal_id=3, direction="BEAR", option_strike=5400,
                              option_type="put", entry_premium=4.0, contracts=1)
    broker.close_position(p3, 1.0, "stop")             # -$300
    p4 = broker.open_position(signal_id=4, direction="BULL", option_strike=5500,
                              option_type="call", entry_premium=2.0, contracts=1)
    broker.close_position(p4, 0.0, "expired")          # -$200
    broker.open_position(signal_id=5, direction="BULL", option_strike=5450,
                         option_type="call", entry_premium=3.0, contracts=1)
    s = broker.get_pnl_summary()
    assert s["total"] == 5
    assert s["open"] == 1
    assert s["won"] == 2
    assert s["lost"] == 1
    assert s["expired"] == 1
    assert s["pnl_usd"] == pytest.approx(600.0)        # 500 + 600 - 300 - 200
    assert s["win_rate_pct"] == pytest.approx(50.0)    # 2 won / 4 closed
