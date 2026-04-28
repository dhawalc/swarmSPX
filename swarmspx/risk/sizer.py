"""Kelly position sizer with daily lock.

Why fractional Kelly:
    Full Kelly maximizes geometric growth at the cost of catastrophic
    drawdowns (50%+ is normal, ruin is non-trivial). Fractional Kelly
    (default 0.10) trades growth for survival. War room risk-seat verdict:
    at 0.10 Kelly on $25k bankroll, eight consecutive losses (a once-per-quarter
    event at 65% loss rate) ≈ 15% drawdown. At full Kelly the same streak
    ≈ 57% drawdown — psychological ruin.

Why daily lock:
    Position size written to data/sizing_lock_YYYY-MM-DD.json at the first
    sizing call of the ET day, then immutable for the rest of the day. No
    discretionary mid-session overrides. Discipline lives in code, not in
    willpower (review #11).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from swarmspx.clock import now_et

logger = logging.getLogger(__name__)


# ── Defaults ─────────────────────────────────────────────────────────────────

DEFAULT_BANKROLL_USD = 25_000.0          # starting bankroll
DEFAULT_KELLY_FRACTION = 0.10            # 1/10 Kelly — survival-first
DEFAULT_MAX_PER_TRADE_PCT = 0.05         # absolute hard cap: never risk >5% on one trade
DEFAULT_KELLY_CAP = 0.40                 # cap raw Kelly at 40%

# Conservative until backtest provides honest stats (review H1: backtest is circular)
DEFAULT_WIN_PROB = 0.40
DEFAULT_PAYOFF_RATIO = 3.0


@dataclass
class SizingDecision:
    risk_usd: float          # max dollars at risk on this trade
    contracts: int           # whole contracts (rounded down)
    bankroll: float          # bankroll used in the calculation
    kelly_used: float        # the fractional-Kelly multiplier applied
    locked_for_date: str     # ET date (YYYY-MM-DD) the cap is locked to
    reason: str              # 'normal' / 'low_confidence' / 'no_premium' / 'below_min_size'


class KellyPositionSizer:
    """Daily-locked fractional Kelly sizer for SPX 0DTE."""

    def __init__(
        self,
        bankroll_usd: float = DEFAULT_BANKROLL_USD,
        kelly_fraction: float = DEFAULT_KELLY_FRACTION,
        win_prob: float = DEFAULT_WIN_PROB,
        payoff_ratio: float = DEFAULT_PAYOFF_RATIO,
        max_per_trade_pct: float = DEFAULT_MAX_PER_TRADE_PCT,
        kelly_cap: float = DEFAULT_KELLY_CAP,
        lock_dir: str = "data",
    ):
        self.bankroll = float(bankroll_usd)
        self.kelly_fraction = float(kelly_fraction)
        self.win_prob = float(win_prob)
        self.payoff_ratio = float(payoff_ratio)
        self.max_per_trade_pct = float(max_per_trade_pct)
        self.kelly_cap = float(kelly_cap)
        self.lock_dir = Path(lock_dir)
        self.lock_dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ───────────────────────────────────────────────────────

    def size_for_signal(
        self,
        entry_premium: float,
        confidence: Optional[float] = None,
    ) -> SizingDecision:
        """Compute risk in dollars + contract count for a signal."""
        date_key = now_et().date().isoformat()
        cap = self._get_or_lock_daily_cap(date_key)

        if confidence is not None and confidence < 55.0:
            return SizingDecision(
                risk_usd=0.0,
                contracts=0,
                bankroll=cap["bankroll"],
                kelly_used=0.0,
                locked_for_date=date_key,
                reason="low_confidence",
            )

        if entry_premium is None or entry_premium <= 0:
            return SizingDecision(
                risk_usd=0.0,
                contracts=0,
                bankroll=cap["bankroll"],
                kelly_used=0.0,
                locked_for_date=date_key,
                reason="no_premium",
            )

        max_risk_usd = cap["max_per_trade_usd"]

        # Confidence scaling — high-conviction earns full Kelly,
        # low-conviction is reduced. Below 70% conviction we halve.
        if confidence is not None:
            scale = max(0.5, min(1.0, confidence / 100.0 * 1.2))
            max_risk_usd = max_risk_usd * scale

        # SPX options: 1 contract = 100 multiplier → premium × 100 = $ at risk
        per_contract_usd = entry_premium * 100.0
        contracts = int(max_risk_usd // per_contract_usd)

        if contracts < 1:
            return SizingDecision(
                risk_usd=0.0,
                contracts=0,
                bankroll=cap["bankroll"],
                kelly_used=cap["kelly_fraction"],
                locked_for_date=date_key,
                reason="below_min_size",
            )

        actual_risk_usd = round(contracts * per_contract_usd, 2)
        return SizingDecision(
            risk_usd=actual_risk_usd,
            contracts=contracts,
            bankroll=cap["bankroll"],
            kelly_used=cap["kelly_fraction"],
            locked_for_date=date_key,
            reason="normal",
        )

    # ── Daily lock — Ulysses contract for size discipline ────────────────

    def _get_or_lock_daily_cap(self, date_key: str) -> dict:
        """Read today's lock file or create it on the first call of the day."""
        path = self.lock_dir / f"sizing_lock_{date_key}.json"
        if path.exists():
            try:
                with path.open() as f:
                    data = json.load(f)
                required = {"bankroll", "kelly_fraction", "max_per_trade_usd"}
                if required.issubset(data.keys()):
                    return data
                logger.warning("Sizing lock %s corrupt — rebuilding", path)
            except Exception:
                logger.exception("Failed reading sizing lock %s — rebuilding", path)

        # Fresh cap
        edge = (2.0 * self.win_prob) - 1.0
        if self.payoff_ratio <= 0:
            raw_kelly = 0.0
        else:
            raw_kelly = max(0.0, min(self.kelly_cap, edge / self.payoff_ratio))

        fractional = raw_kelly * self.kelly_fraction
        max_per_trade_usd = round(
            min(self.bankroll * self.max_per_trade_pct, self.bankroll * fractional),
            2,
        )

        data = {
            "date": date_key,
            "bankroll": round(self.bankroll, 2),
            "kelly_fraction": round(fractional, 4),
            "raw_kelly": round(raw_kelly, 4),
            "max_per_trade_usd": max_per_trade_usd,
            "max_per_trade_pct": round(max_per_trade_usd / self.bankroll, 4) if self.bankroll else 0.0,
            "locked_at": now_et().isoformat(),
        }

        try:
            with path.open("w") as f:
                json.dump(data, f, indent=2)
            logger.info(
                "Sizing locked for %s: bankroll=$%.0f max_per_trade=$%.2f kelly=%.3f",
                date_key, self.bankroll, max_per_trade_usd, fractional,
            )
        except Exception:
            logger.exception("Failed to persist sizing lock %s — proceeding in-memory", path)

        return data

    def get_today_cap(self) -> dict:
        """Return today's lock file (creates it if missing)."""
        return self._get_or_lock_daily_cap(now_et().date().isoformat())
