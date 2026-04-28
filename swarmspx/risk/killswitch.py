"""Multi-trigger circuit breaker.

Triggers (any one trips the switch — fail-loud, not fail-silent):
    1. Daily loss   ≥ DAILY_LOSS_PCT     → auto-clear next ET trading day open
    2. Weekly loss  ≥ WEEKLY_LOSS_PCT    → manual clear only
    3. Monthly loss ≥ MONTHLY_LOSS_PCT   → manual clear only
    4. Consecutive losses ≥ N            → auto-clear next ET trading day open
    5. Data quality (stale/missing/anomalous feeds) → auto-clear after 5min
    6. Manual trigger (Telegram / CLI)   → manual clear only

State persists across process restarts via data/killswitch_state.json.
War room verdict: discipline that lives in code, not willpower (review #11).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from swarmspx.clock import now_et

logger = logging.getLogger(__name__)


# ── Trigger thresholds (defaults; override via constructor) ──────────────────

DEFAULT_DAILY_LOSS_PCT = 3.0
DEFAULT_WEEKLY_LOSS_PCT = 6.0
DEFAULT_MONTHLY_LOSS_PCT = 10.0
DEFAULT_MAX_CONSECUTIVE_LOSSES = 3

_AUTO_CLEAR_TRIGGERS = frozenset({
    "daily_loss",
    "consecutive_losses",
    "data_quality",
})
_MANUAL_CLEAR_TRIGGERS = frozenset({
    "weekly_loss",
    "monthly_loss",
    "manual",
})

_VALID_TRIGGERS = _AUTO_CLEAR_TRIGGERS | _MANUAL_CLEAR_TRIGGERS


class KillSwitch:
    """Persistent multi-trigger circuit breaker with auto-clear semantics."""

    def __init__(
        self,
        state_path: str = "data/killswitch_state.json",
        daily_loss_pct: float = DEFAULT_DAILY_LOSS_PCT,
        weekly_loss_pct: float = DEFAULT_WEEKLY_LOSS_PCT,
        monthly_loss_pct: float = DEFAULT_MONTHLY_LOSS_PCT,
        max_consecutive_losses: int = DEFAULT_MAX_CONSECUTIVE_LOSSES,
    ):
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.daily_loss_pct = float(daily_loss_pct)
        self.weekly_loss_pct = float(weekly_loss_pct)
        self.monthly_loss_pct = float(monthly_loss_pct)
        self.max_consecutive_losses = int(max_consecutive_losses)
        self._state: Optional[dict] = None

    # ── Public API ───────────────────────────────────────────────────────

    def is_tripped(self) -> bool:
        """True if any trigger is active. Auto-clears expired triggers first."""
        state = self._load()
        if not state.get("tripped"):
            return False

        clear_at_raw = state.get("auto_clear_at")
        if clear_at_raw:
            try:
                clear_at = datetime.fromisoformat(clear_at_raw)
                if now_et() >= clear_at:
                    logger.info(
                        "Kill switch auto-cleared (was: %s — %s)",
                        state.get("triggered_by"), state.get("triggered_reason"),
                    )
                    self.reset(by="auto")
                    return False
            except (ValueError, TypeError):
                pass  # malformed timestamp — keep tripped

        return True

    def trip(self, trigger: str, reason: str) -> None:
        """Trip the switch with a named trigger and human-readable reason."""
        if trigger not in _VALID_TRIGGERS:
            logger.warning(
                "KillSwitch.trip received unknown trigger=%r — coercing to 'manual'",
                trigger,
            )
            trigger = "manual"

        prev = self._load()
        trigger_count = int(prev.get("trigger_count", 0)) + 1
        auto_clear = self._compute_auto_clear(trigger)

        state = {
            "tripped": True,
            "triggered_by": trigger,
            "triggered_at": now_et().isoformat(),
            "triggered_reason": str(reason)[:500],
            "auto_clear_at": auto_clear.isoformat() if auto_clear else None,
            "trigger_count": trigger_count,
        }
        self._persist(state)
        logger.error(
            "KILL_SWITCH_TRIPPED trigger=%s reason=%s clear_at=%s",
            trigger, reason, state["auto_clear_at"],
        )

    def reset(self, by: str = "user") -> None:
        """Manually clear the switch. Logs who/why."""
        prev = self._load()
        if not prev.get("tripped"):
            return
        state = {
            "tripped": False,
            "triggered_by": "",
            "triggered_at": "",
            "triggered_reason": "",
            "auto_clear_at": None,
            "trigger_count": int(prev.get("trigger_count", 0)),
            "last_reset_by": by,
            "last_reset_at": now_et().isoformat(),
            "last_trigger": prev.get("triggered_by", ""),
        }
        self._persist(state)
        logger.warning(
            "KILL_SWITCH_RESET by=%s previous_trigger=%s previous_reason=%s",
            by, prev.get("triggered_by"), prev.get("triggered_reason"),
        )

    @property
    def state(self) -> dict:
        return dict(self._load())

    # ── Auto-evaluator hooks ─────────────────────────────────────────────

    def evaluate_loss_bands(
        self,
        daily_pnl_pct: float,
        weekly_pnl_pct: float,
        monthly_pnl_pct: float,
    ) -> bool:
        """Trip if any loss-band threshold is breached. Returns is_tripped()."""
        if self.is_tripped():
            return True
        if monthly_pnl_pct <= -self.monthly_loss_pct:
            self.trip("monthly_loss", f"monthly P&L {monthly_pnl_pct:+.2f}% breached -{self.monthly_loss_pct}%")
            return True
        if weekly_pnl_pct <= -self.weekly_loss_pct:
            self.trip("weekly_loss", f"weekly P&L {weekly_pnl_pct:+.2f}% breached -{self.weekly_loss_pct}%")
            return True
        if daily_pnl_pct <= -self.daily_loss_pct:
            self.trip("daily_loss", f"daily P&L {daily_pnl_pct:+.2f}% breached -{self.daily_loss_pct}%")
            return True
        return False

    def evaluate_consecutive_losses(self, count: int) -> bool:
        """Trip if consecutive-loss count meets/exceeds the threshold."""
        if self.is_tripped():
            return True
        if count >= self.max_consecutive_losses:
            self.trip("consecutive_losses", f"{count} consecutive losses today")
            return True
        return False

    # ── Persistence ──────────────────────────────────────────────────────

    def _load(self) -> dict:
        if self._state is not None:
            return self._state

        if not self.state_path.exists():
            self._state = {
                "tripped": False,
                "triggered_by": "",
                "triggered_at": "",
                "triggered_reason": "",
                "auto_clear_at": None,
                "trigger_count": 0,
            }
            return self._state

        try:
            with self.state_path.open() as f:
                self._state = json.load(f)
        except Exception:
            logger.exception("KillSwitch state corrupt at %s — defaulting to TRIPPED", self.state_path)
            # Fail safe: if we can't read state, assume tripped
            self._state = {
                "tripped": True,
                "triggered_by": "data_quality",
                "triggered_at": now_et().isoformat(),
                "triggered_reason": "killswitch_state.json unreadable",
                "auto_clear_at": None,
                "trigger_count": 0,
            }
        return self._state

    def _persist(self, state: dict) -> None:
        self._state = state
        try:
            with self.state_path.open("w") as f:
                json.dump(state, f, indent=2)
        except Exception:
            logger.exception("Failed to persist killswitch state to %s", self.state_path)

    def _compute_auto_clear(self, trigger: str):
        """Return tz-aware ET datetime when the trigger auto-clears, or None."""
        if trigger not in _AUTO_CLEAR_TRIGGERS:
            return None

        now = now_et()
        if trigger == "daily_loss" or trigger == "consecutive_losses":
            return self._next_trading_day_open(now)
        if trigger == "data_quality":
            return now + timedelta(minutes=5)
        return None

    @staticmethod
    def _next_trading_day_open(now):
        """Next Mon-Fri at 09:30 ET strictly in the future."""
        candidate = now.replace(hour=9, minute=30, second=0, microsecond=0)
        if candidate <= now:
            candidate = candidate + timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate = candidate + timedelta(days=1)
        return candidate
