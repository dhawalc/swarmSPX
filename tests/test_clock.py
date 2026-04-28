"""Tests for swarmspx.clock — ET-anchored time helpers."""

from datetime import datetime

from swarmspx.clock import (
    ET,
    UTC,
    get_session,
    is_after_hours,
    is_market_hours,
    now_et,
    to_et,
)


# ── now_et ───────────────────────────────────────────────────────────────────

def test_now_et_is_timezone_aware():
    t = now_et()
    assert t.tzinfo is not None
    assert t.tzinfo.key == "America/New_York"


# ── to_et ────────────────────────────────────────────────────────────────────

def test_to_et_converts_naive_as_utc():
    naive = datetime(2026, 6, 1, 14, 0)  # 14:00 UTC = 10:00 EDT
    converted = to_et(naive)
    assert converted.hour == 10
    assert converted.tzinfo.key == "America/New_York"


def test_to_et_converts_aware_correctly():
    aware = datetime(2026, 6, 1, 14, 0, tzinfo=UTC)
    converted = to_et(aware)
    assert converted.hour == 10  # EDT in June


# ── is_market_hours ──────────────────────────────────────────────────────────

def test_market_hours_open_at_10am_weekday():
    monday = datetime(2026, 6, 1, 10, 0, tzinfo=ET)  # Monday
    assert monday.weekday() == 0
    assert is_market_hours(monday) is True


def test_market_hours_closed_before_open():
    early = datetime(2026, 6, 1, 9, 29, tzinfo=ET)
    assert is_market_hours(early) is False


def test_market_hours_open_exactly_at_930():
    bell = datetime(2026, 6, 1, 9, 30, tzinfo=ET)
    assert is_market_hours(bell) is True


def test_market_hours_closed_after_4pm():
    after = datetime(2026, 6, 1, 16, 1, tzinfo=ET)
    assert is_market_hours(after) is False


def test_market_hours_closed_on_saturday():
    sat = datetime(2026, 6, 6, 12, 0, tzinfo=ET)
    assert sat.weekday() == 5
    assert is_market_hours(sat) is False


def test_market_hours_closed_on_sunday():
    sun = datetime(2026, 6, 7, 12, 0, tzinfo=ET)
    assert sun.weekday() == 6
    assert is_market_hours(sun) is False


def test_market_hours_handles_utc_input_correctly():
    # 14:00 UTC = 10:00 EDT (June, DST)
    utc_dt = datetime(2026, 6, 1, 14, 0, tzinfo=UTC)
    assert is_market_hours(utc_dt) is True


def test_market_hours_dst_transition():
    """Critical regression: a UTC server with naive datetime.now() would say
    the market was open at 13:00 UTC year-round, but EST/EDT shifts that.
    """
    # November (EST): 14:00 UTC = 09:00 EST = before open
    november = datetime(2026, 11, 17, 14, 0, tzinfo=UTC)  # Tuesday
    assert is_market_hours(november) is False
    # June (EDT): 14:00 UTC = 10:00 EDT = open
    june = datetime(2026, 6, 17, 14, 0, tzinfo=UTC)  # Wednesday
    assert is_market_hours(june) is True


# ── get_session ──────────────────────────────────────────────────────────────

def test_get_session_morning_at_9_30():
    bell = datetime(2026, 6, 1, 9, 30, tzinfo=ET)
    assert get_session(bell) == "morning"


def test_get_session_morning_at_11_29():
    almost = datetime(2026, 6, 1, 11, 29, tzinfo=ET)
    assert get_session(almost) == "morning"


def test_get_session_midday_at_11_30():
    boundary = datetime(2026, 6, 1, 11, 30, tzinfo=ET)
    assert get_session(boundary) == "midday"


def test_get_session_midday_at_12_59():
    almost_pm = datetime(2026, 6, 1, 12, 59, tzinfo=ET)
    assert get_session(almost_pm) == "midday"


def test_get_session_afternoon_at_1pm():
    afternoon = datetime(2026, 6, 1, 13, 0, tzinfo=ET)
    assert get_session(afternoon) == "afternoon"


def test_get_session_afternoon_at_3pm():
    late = datetime(2026, 6, 1, 15, 0, tzinfo=ET)
    assert get_session(late) == "afternoon"


def test_get_session_with_utc_input():
    """Critical: UTC input must be converted to ET before sessioning.
    14:00 UTC (June, EDT) = 10:00 ET = morning. The naive bug would call
    this 'midday' (>11:30 in UTC clock minutes-of-day).
    """
    utc_morning_et = datetime(2026, 6, 1, 14, 0, tzinfo=UTC)
    assert get_session(utc_morning_et) == "morning"


# ── is_after_hours ───────────────────────────────────────────────────────────

def test_is_after_hours_during_session_false():
    open_dt = datetime(2026, 6, 1, 12, 0, tzinfo=ET)
    assert is_after_hours(open_dt) is False


def test_is_after_hours_pre_market():
    pre = datetime(2026, 6, 1, 8, 0, tzinfo=ET)
    assert is_after_hours(pre) is True


def test_is_after_hours_post_market():
    post = datetime(2026, 6, 1, 17, 0, tzinfo=ET)
    assert is_after_hours(post) is True


def test_is_after_hours_weekend():
    sat = datetime(2026, 6, 6, 12, 0, tzinfo=ET)
    assert is_after_hours(sat) is True
