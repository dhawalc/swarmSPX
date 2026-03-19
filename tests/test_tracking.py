import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from swarmspx.db import Database
from swarmspx.events import EventBus, OutcomeResolved
from swarmspx.tracking.outcome_tracker import OutcomeTracker


@pytest.fixture
def db():
    d = Database(":memory:")
    d.init_schema()
    return d


@pytest.fixture
def tracker(db):
    fetcher = MagicMock()
    memory = MagicMock()
    bus = EventBus()
    t = OutcomeTracker(db, fetcher, memory, bus)
    return t


def _insert_signal(db, direction="BULL", entry_price=5800.0, hours_ago=3, memory_id="mem_123"):
    """Insert a pending signal with a timestamp N hours in the past."""
    ts = (datetime.now() - timedelta(hours=hours_ago)).isoformat()
    return db.store_simulation_result({
        "direction": direction,
        "confidence": 75.0,
        "agreement_pct": 80.0,
        "spx_entry_price": entry_price,
        "memory_id": memory_id,
        "trade_setup": {"action": "BUY"},
        "agent_votes": {"BULL": 18, "BEAR": 4, "NEUTRAL": 2},
    })


@pytest.mark.asyncio
async def test_outcome_tracker_resolves_old_signals(tracker, db):
    """Pending signal older than 2h gets resolved."""
    # Insert a 3-hour-old BULL signal with entry at 5800
    sig_id = _insert_signal(db, direction="BULL", entry_price=5800.0, hours_ago=3)

    # Current price is 5830 → +0.52% → WIN for BULL
    tracker.fetcher.get_snapshot.return_value = {"spx_price": 5830.0}

    # Manually set the signal timestamp to 3 hours ago (store_simulation_result uses datetime.now())
    old_ts = (datetime.now() - timedelta(hours=3)).isoformat()
    conn = db._connect()
    conn.execute("UPDATE simulation_results SET timestamp = ? WHERE id = ?", [old_ts, sig_id])
    db._close(conn)

    resolved = await tracker.check_pending_signals()

    assert len(resolved) == 1
    assert resolved[0]["outcome"] == "win"
    assert resolved[0]["outcome_pct"] > 0

    # Verify DB was updated
    signals = db.get_recent_signals(limit=1)
    assert signals[0]["outcome"] == "win"


@pytest.mark.asyncio
async def test_outcome_tracker_ignores_recent_signals(tracker, db):
    """Signal that's only 5 minutes old should NOT be resolved (before EOD)."""
    sig_id = _insert_signal(db, direction="BULL", entry_price=5800.0, hours_ago=0)

    tracker.fetcher.get_snapshot.return_value = {"spx_price": 5850.0}

    # Ensure EOD check returns False so only age matters
    with patch.object(OutcomeTracker, "_is_eod", return_value=False):
        resolved = await tracker.check_pending_signals()

    assert len(resolved) == 0

    # Signal should still be pending
    pending = db.get_pending_signals()
    assert len(pending) == 1
    assert pending[0]["id"] == sig_id


@pytest.mark.asyncio
async def test_outcome_tracker_bear_win(tracker, db):
    """BEAR signal wins when price drops."""
    sig_id = _insert_signal(db, direction="BEAR", entry_price=5800.0, hours_ago=3)
    old_ts = (datetime.now() - timedelta(hours=3)).isoformat()
    conn = db._connect()
    conn.execute("UPDATE simulation_results SET timestamp = ? WHERE id = ?", [old_ts, sig_id])
    db._close(conn)

    # Price dropped to 5770 → BEAR wins
    tracker.fetcher.get_snapshot.return_value = {"spx_price": 5770.0}

    resolved = await tracker.check_pending_signals()
    assert len(resolved) == 1
    assert resolved[0]["outcome"] == "win"
    assert resolved[0]["outcome_pct"] > 0  # positive P&L for bear


@pytest.mark.asyncio
async def test_outcome_tracker_loss(tracker, db):
    """BULL signal loses when price drops."""
    sig_id = _insert_signal(db, direction="BULL", entry_price=5800.0, hours_ago=3)
    old_ts = (datetime.now() - timedelta(hours=3)).isoformat()
    conn = db._connect()
    conn.execute("UPDATE simulation_results SET timestamp = ? WHERE id = ?", [old_ts, sig_id])
    db._close(conn)

    # Price dropped → BULL loses
    tracker.fetcher.get_snapshot.return_value = {"spx_price": 5750.0}

    resolved = await tracker.check_pending_signals()
    assert len(resolved) == 1
    assert resolved[0]["outcome"] == "loss"
    assert resolved[0]["outcome_pct"] < 0


@pytest.mark.asyncio
async def test_outcome_feeds_back_to_aoms(tracker, db):
    """Verify memory.store_outcome() is called on resolution."""
    sig_id = _insert_signal(db, direction="BULL", entry_price=5800.0, hours_ago=3, memory_id="aoms_456")
    old_ts = (datetime.now() - timedelta(hours=3)).isoformat()
    conn = db._connect()
    conn.execute("UPDATE simulation_results SET timestamp = ? WHERE id = ?", [old_ts, sig_id])
    db._close(conn)

    tracker.fetcher.get_snapshot.return_value = {"spx_price": 5820.0}

    await tracker.check_pending_signals()

    tracker.memory.store_outcome.assert_called_once()
    args = tracker.memory.store_outcome.call_args
    assert args[0][0] == "aoms_456"  # memory_id
    assert args[0][1] == "win"       # outcome


@pytest.mark.asyncio
async def test_outcome_emits_event(tracker, db):
    """Verify OutcomeResolved event is emitted on the bus."""
    sig_id = _insert_signal(db, direction="BULL", entry_price=5800.0, hours_ago=3)
    old_ts = (datetime.now() - timedelta(hours=3)).isoformat()
    conn = db._connect()
    conn.execute("UPDATE simulation_results SET timestamp = ? WHERE id = ?", [old_ts, sig_id])
    db._close(conn)

    tracker.fetcher.get_snapshot.return_value = {"spx_price": 5830.0}

    q = tracker.bus.subscribe()
    await tracker.check_pending_signals()

    event = q.get_nowait()
    assert isinstance(event, OutcomeResolved)
    assert event.signal_id == sig_id
    assert event.outcome == "win"


@pytest.mark.asyncio
async def test_outcome_no_pending_is_noop(tracker):
    """No pending signals → empty list, no errors."""
    tracker.fetcher.get_snapshot.return_value = {"spx_price": 5800.0}
    resolved = await tracker.check_pending_signals()
    assert resolved == []


@pytest.mark.asyncio
async def test_outcome_no_price_skips_resolution(tracker, db):
    """If fetcher returns no price, signals stay pending."""
    _insert_signal(db, direction="BULL", entry_price=5800.0, hours_ago=3)
    tracker.fetcher.get_snapshot.return_value = {"spx_price": 0}

    resolved = await tracker.check_pending_signals()
    assert resolved == []
