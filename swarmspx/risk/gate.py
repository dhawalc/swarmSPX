"""Pre-trade risk gate — synchronous, blocking, fast (~50ms budget).

Sits between consensus generation and order dispatch. Every decision passes
through this gate. If any check rejects, the trade is killed before it leaves
the box. War room consensus: this is the line between a system that survives
a 3am bug and one that doesn't (review #12).

Checks performed (all rejections logged with structured reason):
    1. Kill switch state (any active circuit breaker → reject)
    2. Daily loss band (default -3% of bankroll → reject for the rest of day)
    3. Weekly loss band (default -6% → reject for the rest of week)
    4. Consecutive-loss limit (3 in a row → reject for the rest of session)
    5. Position-count cap (default 5 open → reject new)
    6. Data freshness (snapshot older than 30s → reject — stale market)
    7. Idempotency (same client_order_id within 5min → reject duplicate)
    8. Direction validity (NEUTRAL signals never produce orders)

Usage:
    gate = PreTradeRiskGate(db)
    decision = gate.check(trade_card, market_context)
    if not decision.passed:
        log_and_skip(decision.reasons)
    else:
        dispatch_order(trade_card)
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from swarmspx.clock import now_et, UTC
from swarmspx.db import Database

logger = logging.getLogger(__name__)


# ── Defaults (override via constructor) ──────────────────────────────────────

DEFAULT_DAILY_LOSS_PCT = 3.0       # -3% of bankroll → halt trading
DEFAULT_WEEKLY_LOSS_PCT = 6.0      # -6% / week
DEFAULT_MONTHLY_LOSS_PCT = 10.0    # -10% / month
DEFAULT_MAX_OPEN_POSITIONS = 5     # concurrent open trades cap
DEFAULT_MAX_CONSECUTIVE_LOSSES = 3 # halt for the day after N in a row
DEFAULT_DATA_STALENESS_SEC = 30    # snapshot older than this → reject
DEFAULT_IDEMPOTENCY_WINDOW_SEC = 300  # 5min duplicate-suppression window


@dataclass
class RiskDecision:
    """Outcome of a pre-trade check.

    action  : 'PASS' or 'REJECT'
    reasons : list of structured rejection codes (empty on PASS)
    meta    : optional details for audit logging (e.g. computed loss numbers)
    """
    action: str  # "PASS" | "REJECT"
    reasons: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.action == "PASS"


class PreTradeRiskGate:
    """Synchronous pre-trade risk evaluator.

    Stateful for idempotency (recent client_order_ids cached in memory).
    Loss-band checks query the DB on every call.
    """

    def __init__(
        self,
        db: Database,
        bankroll: float = 25000.0,
        daily_loss_pct: float = DEFAULT_DAILY_LOSS_PCT,
        weekly_loss_pct: float = DEFAULT_WEEKLY_LOSS_PCT,
        monthly_loss_pct: float = DEFAULT_MONTHLY_LOSS_PCT,
        max_open_positions: int = DEFAULT_MAX_OPEN_POSITIONS,
        max_consecutive_losses: int = DEFAULT_MAX_CONSECUTIVE_LOSSES,
        data_staleness_sec: int = DEFAULT_DATA_STALENESS_SEC,
        idempotency_window_sec: int = DEFAULT_IDEMPOTENCY_WINDOW_SEC,
    ):
        self.db = db
        self.bankroll = float(bankroll)
        self.daily_loss_pct = float(daily_loss_pct)
        self.weekly_loss_pct = float(weekly_loss_pct)
        self.monthly_loss_pct = float(monthly_loss_pct)
        self.max_open_positions = int(max_open_positions)
        self.max_consecutive_losses = int(max_consecutive_losses)
        self.data_staleness_sec = int(data_staleness_sec)
        self.idempotency_window_sec = int(idempotency_window_sec)
        self._recent_orders: dict[str, datetime] = {}

    # ── Public entry point ───────────────────────────────────────────────

    def check(
        self,
        trade_card: dict,
        market_context: dict,
        kill_switch_active: bool = False,
    ) -> RiskDecision:
        """Run all pre-trade checks. Returns PASS or REJECT(reasons)."""
        reasons: list[str] = []
        meta: dict = {}

        # 1. Kill switch (highest priority — short-circuit)
        if kill_switch_active:
            return RiskDecision(action="REJECT", reasons=["kill_switch_active"])

        # 2. Direction validity — NEUTRAL never produces an order
        direction = (trade_card.get("direction") or "").upper()
        if direction not in ("BULL", "BEAR"):
            return RiskDecision(
                action="REJECT",
                reasons=["non_directional"],
                meta={"direction": direction},
            )

        # 3. Data freshness
        if not self._check_data_fresh(market_context, meta):
            reasons.append("stale_market_data")

        # 4. Loss bands (daily / weekly / monthly)
        for window_label, max_loss_pct, days in [
            ("daily",   self.daily_loss_pct,   1),
            ("weekly",  self.weekly_loss_pct,  7),
            ("monthly", self.monthly_loss_pct, 30),
        ]:
            pnl_pct = self._compute_window_pnl_pct(days)
            meta[f"{window_label}_pnl_pct"] = round(pnl_pct, 2)
            if pnl_pct <= -max_loss_pct:
                reasons.append(f"{window_label}_loss_band")

        # 5. Consecutive losses
        consec = self._consecutive_losses_today()
        meta["consecutive_losses"] = consec
        if consec >= self.max_consecutive_losses:
            reasons.append("consecutive_loss_limit")

        # 6. Position count
        open_positions = self._count_open_positions()
        meta["open_positions"] = open_positions
        if open_positions >= self.max_open_positions:
            reasons.append("position_count_cap")

        # 7. Idempotency
        client_order_id = self._compute_client_order_id(trade_card, market_context)
        meta["client_order_id"] = client_order_id
        if self._is_duplicate(client_order_id):
            reasons.append("duplicate_order")
        else:
            self._record_order(client_order_id)

        if reasons:
            logger.warning("PRE_TRADE_REJECT reasons=%s meta=%s", reasons, meta)
            return RiskDecision(action="REJECT", reasons=reasons, meta=meta)

        return RiskDecision(action="PASS", reasons=[], meta=meta)

    # ── Individual checks ────────────────────────────────────────────────

    def _check_data_fresh(self, market_context: dict, meta: dict) -> bool:
        """True if market_context.timestamp is within data_staleness_sec."""
        ts = market_context.get("timestamp")
        if not ts:
            meta["data_age_sec"] = None
            return False
        try:
            snap_dt = datetime.fromisoformat(str(ts))
            if snap_dt.tzinfo is None:
                snap_dt = snap_dt.replace(tzinfo=UTC)
            age = (now_et() - snap_dt).total_seconds()
            meta["data_age_sec"] = round(age, 1)
            return age <= self.data_staleness_sec
        except (ValueError, TypeError):
            meta["data_age_sec"] = None
            return False

    def _compute_window_pnl_pct(self, days: int) -> float:
        """Bankroll-impact P&L across resolved signals in the last N days.

        Heuristic until the Kelly sizer (task #10) records actual position
        sizes: each signal sized at fractional Kelly ≈ 2% of bankroll →
        bankroll-impact = outcome_pct × 0.02. Replace with size-weighted
        sum once positions are tracked.
        """
        try:
            signals = self.db.get_recent_signals(limit=200)
        except Exception:
            logger.exception("get_recent_signals failed in risk gate")
            return 0.0

        cutoff = now_et() - timedelta(days=days)
        total = 0.0
        for s in signals:
            ts = self._parse_ts(s.get("timestamp"))
            if ts is None or ts < cutoff:
                continue
            outcome = s.get("outcome")
            if outcome not in ("win", "loss"):
                continue
            pct = float(s.get("outcome_pct", 0) or 0)
            total += pct * 0.02
        return total

    def _consecutive_losses_today(self) -> int:
        """Count the longest consecutive-losses streak ending now (today, ET)."""
        try:
            signals = self.db.get_recent_signals(limit=20)
        except Exception:
            return 0
        today_et = now_et().date()
        streak = 0
        for s in signals:  # already DESC
            ts = self._parse_ts(s.get("timestamp"))
            if ts is None:
                break
            if ts.astimezone(now_et().tzinfo).date() != today_et:
                break
            if s.get("outcome") == "loss":
                streak += 1
            elif s.get("outcome") == "win":
                break
            # 'pending'/'scratch' neither extend nor break the streak
        return streak

    def _count_open_positions(self) -> int:
        """Count signals still in 'pending' state (proxy for open positions)."""
        try:
            return len(self.db.get_pending_signals(max_age_hours=24))
        except Exception:
            logger.exception("get_pending_signals failed in risk gate")
            return 0

    @staticmethod
    def _parse_ts(ts_raw) -> Optional[datetime]:
        """Parse an ISO-8601 timestamp string to a tz-aware datetime (UTC if naive)."""
        if ts_raw is None:
            return None
        try:
            ts = datetime.fromisoformat(str(ts_raw))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            return ts
        except (ValueError, TypeError):
            return None

    def _compute_client_order_id(
        self,
        trade_card: dict,
        market_context: dict,
    ) -> str:
        """Deterministic id from (direction, structure, strike, minute-bucket).

        Trades within the same minute with same legs collapse to one id —
        repeats in that window get rejected as duplicates.
        """
        ts = market_context.get("timestamp", "")
        try:
            ts_dt = datetime.fromisoformat(str(ts))
            bucket = ts_dt.replace(second=0, microsecond=0).isoformat()
        except (ValueError, TypeError):
            bucket = str(ts)
        seed = "|".join([
            (trade_card.get("direction") or ""),
            str(trade_card.get("strategy_type", "")),
            str(trade_card.get("strike", "")),
            str(trade_card.get("option_type", "")),
            bucket,
        ])
        return hashlib.sha256(seed.encode()).hexdigest()[:16]

    def _is_duplicate(self, client_order_id: str) -> bool:
        seen_at = self._recent_orders.get(client_order_id)
        if seen_at is None:
            return False
        age = (now_et() - seen_at).total_seconds()
        return age <= self.idempotency_window_sec

    def _record_order(self, client_order_id: str) -> None:
        self._recent_orders[client_order_id] = now_et()
        cutoff = now_et() - timedelta(seconds=self.idempotency_window_sec * 2)
        stale = [k for k, v in self._recent_orders.items() if v < cutoff]
        for k in stale:
            del self._recent_orders[k]
