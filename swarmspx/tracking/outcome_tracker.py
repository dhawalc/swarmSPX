"""Outcome tracker — resolves pending signals by comparing entry price to current SPX price."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from swarmspx.db import Database
from swarmspx.ingest.market_data import MarketDataFetcher
from swarmspx.memory import AOMemory
from swarmspx.events import EventBus, OutcomeResolved

logger = logging.getLogger(__name__)

# Resolution thresholds
RESOLUTION_AGE_HOURS = 2       # resolve after 2 hours
SCRATCH_THRESHOLD_PCT = 0.05   # +/- 0.05% = scratch


class OutcomeTracker:
    """Checks pending signals and resolves them based on current SPX price.

    Resolution logic:
    - WIN: P&L > +0.05% in the signal's direction
    - LOSS: P&L < -0.05% against the signal's direction
    - SCRATCH: P&L within +/- 0.05%
    - Only resolves signals older than RESOLUTION_AGE_HOURS (2h) or at EOD
    """

    def __init__(
        self,
        db: Database,
        fetcher: MarketDataFetcher,
        memory: AOMemory,
        bus: EventBus,
    ) -> None:
        self.db = db
        self.fetcher = fetcher
        self.memory = memory
        self.bus = bus

    async def check_pending_signals(self) -> list[dict]:
        """Check all pending signals and resolve those that are old enough.

        Returns list of resolved signal dicts.
        """
        pending = self.db.get_pending_signals(max_age_hours=24)
        if not pending:
            return []

        # Get current SPX price
        current_price = self._get_current_price()
        if current_price is None or current_price <= 0:
            logger.warning("Cannot resolve signals — no current SPX price")
            return []

        now = datetime.now()
        resolved = []

        for signal in pending:
            signal_time = self._parse_timestamp(signal["timestamp"])
            if signal_time is None:
                continue

            age_hours = (now - signal_time).total_seconds() / 3600
            is_eod = self._is_eod(now)

            if age_hours < RESOLUTION_AGE_HOURS and not is_eod:
                continue

            entry_price = signal.get("spx_entry_price", 0)
            if entry_price <= 0:
                continue

            # Compute P&L based on direction
            raw_pct = ((current_price - entry_price) / entry_price) * 100
            direction = signal.get("direction", "NEUTRAL")

            if direction == "BEAR":
                pnl_pct = -raw_pct  # bears profit when price drops
            elif direction == "BULL":
                pnl_pct = raw_pct
            else:
                pnl_pct = 0.0

            # Determine outcome
            if abs(pnl_pct) <= SCRATCH_THRESHOLD_PCT:
                outcome = "scratch"
            elif pnl_pct > 0:
                outcome = "win"
            else:
                outcome = "loss"

            pnl_pct = round(pnl_pct, 3)

            # Persist
            self.db.update_outcome(signal["id"], outcome, pnl_pct)

            # Feed back to AOMS
            memory_id = signal.get("memory_id")
            if memory_id:
                self.memory.store_outcome(memory_id, outcome, pnl_pct)

            # Emit event
            await self.bus.emit(OutcomeResolved(
                signal_id=signal["id"],
                direction=direction,
                outcome=outcome,
                outcome_pct=pnl_pct,
            ))

            resolved.append({
                "signal_id": signal["id"],
                "direction": direction,
                "outcome": outcome,
                "outcome_pct": pnl_pct,
            })

            logger.info(
                "Signal %d resolved: %s %s %+.2f%%",
                signal["id"], direction, outcome.upper(), pnl_pct,
            )

        return resolved

    def _get_current_price(self) -> Optional[float]:
        """Fetch latest SPX price from the market data fetcher."""
        try:
            snapshot = self.fetcher.get_snapshot()
            return snapshot.get("spx_price")
        except Exception:
            logger.exception("Failed to fetch current SPX price")
            return None

    @staticmethod
    def _is_eod(now: datetime) -> bool:
        """Check if we're at or past end of day (4 PM ET simplified)."""
        return now.hour >= 16

    @staticmethod
    def _parse_timestamp(ts) -> Optional[datetime]:
        """Parse an ISO timestamp string to datetime."""
        if isinstance(ts, datetime):
            return ts
        try:
            return datetime.fromisoformat(str(ts))
        except (ValueError, TypeError):
            return None
