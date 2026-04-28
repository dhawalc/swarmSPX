"""Timezone-aware clock helpers anchored on US Eastern.

Why this exists:
    The trading system was using `datetime.now()` (naive, server-local) for
    session detection and market-hours checks. On a UTC VPS that means the
    "morning" window ends at 07:30 UTC = 03:30 AM ET — every morning trade
    misroutes to lotto mode (review #8).

    All session/window/market-hours logic must use ET. Persistence layer
    (DB timestamps) can stay UTC-naive as long as it's consistent — that's
    a separate concern.

Usage:
    from swarmspx.clock import now_et, is_market_hours, get_session
    if is_market_hours():
        ...
    if get_session() == "morning":
        ...
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

# Session boundaries in ET — minutes since midnight
_MORNING_END = 11 * 60 + 30   # 11:30 AM ET — morning ends, midday begins
_MIDDAY_END = 13 * 60          # 1:00 PM ET — midday ends, afternoon begins

# Market hours in ET (regular session)
_MARKET_OPEN = 9 * 60 + 30     # 9:30 AM ET
_MARKET_CLOSE = 16 * 60        # 4:00 PM ET


def now_et() -> datetime:
    """Return the current wall-clock time in US/Eastern, timezone-aware.

    Uses ZoneInfo so DST transitions are handled automatically.
    """
    return datetime.now(tz=ET)


def now_utc() -> datetime:
    """Current UTC time as a timezone-aware datetime."""
    return datetime.now(tz=UTC)


def to_et(dt: datetime) -> datetime:
    """Convert any datetime (naive assumed UTC, or aware) to ET."""
    if dt.tzinfo is None:
        # Treat naive as UTC — safest default for server-side timestamps
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(ET)


def is_market_hours(dt: datetime | None = None) -> bool:
    """Return True if `dt` (or current ET time) is within regular SPX hours.

    Regular session: Mon-Fri 09:30-16:00 ET. Holidays are NOT excluded —
    that's a separate calendar concern; the function just checks weekday + time.
    """
    if dt is None:
        dt = now_et()
    else:
        dt = to_et(dt)

    # Weekday: Monday=0 ... Friday=4. Saturday/Sunday closed.
    if dt.weekday() >= 5:
        return False

    minute_of_day = dt.hour * 60 + dt.minute
    return _MARKET_OPEN <= minute_of_day <= _MARKET_CLOSE


def get_session(dt: datetime | None = None) -> str:
    """Classify ET time into morning / midday / afternoon trading sessions.

    Boundaries:
      morning   — before 11:30 AM ET
      midday    — 11:30 AM to 1:00 PM ET
      afternoon — 1:00 PM ET onwards

    These are consumed by the strategy selector to choose between straight
    OTM (morning), iron condor (midday/chop), and lotto (afternoon decay).
    """
    if dt is None:
        dt = now_et()
    else:
        dt = to_et(dt)

    minute_of_day = dt.hour * 60 + dt.minute
    if minute_of_day < _MORNING_END:
        return "morning"
    if minute_of_day < _MIDDAY_END:
        return "midday"
    return "afternoon"


def is_after_hours(dt: datetime | None = None) -> bool:
    """True if currently past market close ET (or before open) on a weekday."""
    if dt is None:
        dt = now_et()
    else:
        dt = to_et(dt)
    if dt.weekday() >= 5:
        return True
    minute_of_day = dt.hour * 60 + dt.minute
    return minute_of_day < _MARKET_OPEN or minute_of_day > _MARKET_CLOSE
