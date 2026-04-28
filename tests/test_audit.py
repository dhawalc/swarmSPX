"""Tests for swarmspx.audit — per-decision JSONL audit log."""

import json
from dataclasses import dataclass

from swarmspx.audit import AuditLog, _json_safe
from swarmspx.clock import now_et


def test_append_creates_dated_file(tmp_path):
    log = AuditLog(base_dir=str(tmp_path))
    log.append(
        cycle_id=1,
        market_context={"spx_price": 5450.0},
        consensus={"direction": "BULL", "confidence": 75.0},
        strategy={"strategy": "STRAIGHT"},
        sizing={"contracts": 2, "risk_usd": 1100.0},
        risk_decision={"action": "PASS"},
        signal_id=99,
        entry_premium=5.5,
        option_strike=5450.0,
        option_type="call",
        outcome="pending",
    )
    today = now_et().date().isoformat()
    path = tmp_path / f"{today}.jsonl"
    assert path.exists()
    content = path.read_text().strip()
    assert content
    record = json.loads(content)
    assert record["cycle_id"] == 1
    assert record["signal_id"] == 99
    assert record["outcome"] == "pending"


def test_append_is_idempotent_appendonly(tmp_path):
    log = AuditLog(base_dir=str(tmp_path))
    for i in range(5):
        log.append(
            cycle_id=i,
            market_context={},
            consensus={},
            strategy={},
            sizing={},
            risk_decision={"action": "PASS"},
            signal_id=i,
            entry_premium=1.0,
            option_strike=5450.0,
            option_type="call",
            outcome="pending",
        )
    today = now_et().date().isoformat()
    rows = log.read_day(today)
    assert len(rows) == 5
    assert [r["cycle_id"] for r in rows] == [0, 1, 2, 3, 4]


def test_today_returns_only_today(tmp_path):
    log = AuditLog(base_dir=str(tmp_path))
    log.append(
        cycle_id=1, market_context={}, consensus={}, strategy={},
        sizing={}, risk_decision={}, signal_id=1,
        entry_premium=0, option_strike=0, option_type="", outcome="pending",
    )
    rows = log.today()
    assert len(rows) == 1


def test_read_day_missing_returns_empty(tmp_path):
    log = AuditLog(base_dir=str(tmp_path))
    assert log.read_day("2099-01-01") == []


def test_malformed_line_skipped(tmp_path):
    log = AuditLog(base_dir=str(tmp_path))
    log.append(
        cycle_id=1, market_context={}, consensus={}, strategy={},
        sizing={}, risk_decision={}, signal_id=1,
        entry_premium=0, option_strike=0, option_type="", outcome="pending",
    )
    today = now_et().date().isoformat()
    path = tmp_path / f"{today}.jsonl"
    path.write_text(path.read_text() + "{not valid\n")
    rows = log.read_day(today)
    # The valid row is recovered; the malformed line is skipped
    assert len(rows) == 1
    assert rows[0]["cycle_id"] == 1


# ── _json_safe ───────────────────────────────────────────────────────────────

def test_json_safe_primitives():
    assert _json_safe(None) is None
    assert _json_safe(True) is True
    assert _json_safe(42) == 42
    assert _json_safe(3.14) == 3.14
    assert _json_safe("text") == "text"


def test_json_safe_nested_dict_list():
    val = {"a": [1, 2, {"b": "c"}]}
    assert _json_safe(val) == val


def test_json_safe_dataclass_becomes_dict():
    @dataclass
    class Foo:
        x: int = 1
        y: str = "two"
    out = _json_safe(Foo())
    assert out == {"x": 1, "y": "two"}


def test_json_safe_unknown_type_falls_back_to_str():
    class Weird:
        def __str__(self):
            return "weird"
    assert _json_safe(Weird()) == "weird"
