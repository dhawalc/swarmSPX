"""Per-decision audit log — JSONL, one file per ET date.

Every cycle that produces a signal (pending OR gated) appends a single line
to ``data/decisions/YYYY-MM-DD.jsonl``. The line is a self-contained snapshot
of the decision: market context, consensus, strategy, sizing, risk-gate
verdict, signal id, and (initial) outcome.

Why JSONL not Parquet:
    - Append-only, no rewrite required per row.
    - Inspectable by `tail -f`, `jq`, `wc -l` without Python.
    - Easy to convert to Parquet later for the backtester replay.

Why per-ET-date partitioning:
    Aligns with the trading day boundary. Weekly summary scripts just glob
    `*.jsonl` for the week.

Why a separate module from db.py:
    DuckDB is the analytics layer; this is the audit layer. Audit needs
    strict append-only semantics + human-readable rows. Different access
    patterns, different file. The two CAN diverge if a DB write fails —
    that is a feature: the audit log is the ground truth, not the DB.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from swarmspx.clock import now_et

logger = logging.getLogger(__name__)


class AuditLog:
    """Append-only per-decision JSONL log."""

    def __init__(self, base_dir: str = "data/decisions"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ───────────────────────────────────────────────────────

    def append(
        self,
        *,
        cycle_id: int,
        market_context: dict,
        consensus: dict,
        strategy: dict,
        sizing: dict,
        risk_decision: dict,
        signal_id: Optional[int],
        entry_premium: float,
        option_strike: float,
        option_type: str,
        outcome: str,
    ) -> None:
        """Append one decision row to today's JSONL file. Never raises."""
        ts = now_et()
        record = {
            "cycle_id": cycle_id,
            "timestamp": ts.isoformat(),
            "market_context": _json_safe(market_context),
            "consensus": _json_safe(consensus),
            "strategy": _json_safe(strategy),
            "sizing": _json_safe(sizing),
            "risk_decision": _json_safe(risk_decision),
            "signal_id": signal_id,
            "entry_premium": float(entry_premium or 0.0),
            "option_strike": float(option_strike or 0.0),
            "option_type": option_type or "",
            "outcome": outcome or "",
        }
        path = self._path_for(ts)
        try:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str))
                f.write("\n")
        except Exception:
            logger.exception("Audit log append failed for cycle %d", cycle_id)

    def read_day(self, date_iso: str) -> list[dict]:
        """Read all decisions for a given ET date (YYYY-MM-DD). Empty if missing."""
        path = self.base_dir / f"{date_iso}.jsonl"
        if not path.exists():
            return []
        rows: list[dict] = []
        try:
            with path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        logger.warning("Skipping malformed audit line in %s", path)
        except Exception:
            logger.exception("Failed reading audit day %s", date_iso)
        return rows

    def today(self) -> list[dict]:
        """Read all decisions logged today (ET)."""
        return self.read_day(now_et().date().isoformat())

    # ── Internal ─────────────────────────────────────────────────────────

    def _path_for(self, ts) -> Path:
        return self.base_dir / f"{ts.date().isoformat()}.jsonl"


def _json_safe(value: Any) -> Any:
    """Recursively coerce a value into JSON-safe types.

    Dataclass instances become dicts via ``asdict``. Unknown types fall
    back to ``str()``. Defensive — never raises.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "__dataclass_fields__"):
        from dataclasses import asdict
        try:
            return _json_safe(asdict(value))
        except Exception:
            return str(value)
    return str(value)
