"""Outcome tracker — resolves pending signals by comparing entry price to current SPX price."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from swarmspx.db import Database
from swarmspx.ingest.market_data import MarketDataFetcher
from swarmspx.memory import AOMemory
from swarmspx.events import EventBus, OutcomeResolved
from swarmspx.scoring import AgentScorer

logger = logging.getLogger(__name__)

# Resolution thresholds
RESOLUTION_AGE_HOURS = 2       # resolve after 2 hours

# Legacy SPX-move scratch threshold — used only as a fallback when the signal
# has no option metadata (pre-migration data, or strategy was WAIT/GUIDANCE).
SCRATCH_THRESHOLD_PCT = 0.05   # +/- 0.05% SPX move = scratch

# Option-premium scratch threshold. 0DTE option premium swings of ±10% within
# 2 hours are typically noise (theta + spread); only larger moves indicate the
# trade thesis was right or wrong.
OPTION_SCRATCH_THRESHOLD_PCT = 10.0


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
        scorer: Optional[AgentScorer] = None,
    ) -> None:
        self.db = db
        self.fetcher = fetcher
        self.memory = memory
        self.bus = bus
        self.scorer = scorer

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

            direction = signal.get("direction", "NEUTRAL")

            # Resolve outcome — option-based when we have premium metadata,
            # SPX-based as legacy fallback (review #1).
            resolution = await self._resolve_outcome(signal, current_price)
            outcome = resolution["outcome"]
            pnl_pct = resolution["pnl_pct"]
            exit_premium = resolution["exit_premium"]
            resolution_method = resolution["method"]

            if outcome is None:
                # Resolution deferred (e.g. option chain unavailable, no
                # entry premium recorded, and SPX path also failed).
                logger.info(
                    "Signal #%d resolution deferred (no usable price data)",
                    signal["id"],
                )
                continue

            # ── Persistence order matters for crash safety. ──────────────────
            # 1) Update Darwinian ELO FIRST (and sync to DB inside scorer).
            # 2) Mark signal resolved (this hides it from get_pending_signals).
            # 3) AOMS memory + bus event are best-effort and may fail safely.
            #
            # Crash between (1) and (2): signal stays pending, ELO updated.
            #   Next cycle will recompute outcome (possibly different if SPX
            #   moved) and double-credit agents. Acceptable trade-off vs the
            #   prior order, which would lose ELO PERMANENTLY when the signal
            #   was marked resolved before ELO sync.
            # See NEXT-STEPS.md for the future transactional fix using a
            # `scored` column in simulation_results.

            # 1) ELO update first — failure aborts resolution so we retry next cycle
            if self.scorer and outcome in ("win", "loss"):
                try:
                    agent_votes = self.db.get_agent_votes_for_signal(signal["id"])
                    if agent_votes:
                        regime = agent_votes[0].get("regime", "unknown")
                        self.scorer.process_signal_outcome(
                            signal_id=signal["id"],
                            outcome=outcome,
                            regime=regime,
                            agent_votes=agent_votes,
                            consensus_direction=direction,
                        )
                        logger.info(
                            "Updated %d agent ELO scores for signal #%d (%s)",
                            len(agent_votes), signal["id"], outcome,
                        )
                except Exception:
                    logger.exception(
                        "ELO update failed for signal #%d; deferring resolution",
                        signal["id"],
                    )
                    continue  # don't mark resolved — next cycle retries

            # 2) Mark resolved (after ELO succeeded — order matters)
            self.db.update_outcome(signal["id"], outcome, pnl_pct, exit_premium=exit_premium)

            # 3) Best-effort tail: AOMS memory + bus event (now async)
            memory_id = signal.get("memory_id")
            if memory_id:
                try:
                    await self.memory.store_outcome(memory_id, outcome, pnl_pct)
                except Exception:
                    logger.exception("AOMS store_outcome failed for signal #%d", signal["id"])

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
                "exit_premium": exit_premium,
                "method": resolution_method,
            })

            logger.info(
                "Signal %d resolved [%s]: %s %s %+.2f%% (exit_premium=%.2f)",
                signal["id"], resolution_method, direction,
                outcome.upper(), pnl_pct, exit_premium,
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

    async def _resolve_outcome(self, signal: dict, current_spx_price: float) -> dict:
        """Compute outcome for a pending signal.

        Two paths:
          1. Option-based — when signal carries entry_premium + option_strike
             + option_type. Fetches the contract's current premium and
             computes outcome from premium delta. This is the honest path
             (review #1: training was on SPX move, not option P&L).
          2. SPX fallback — for legacy signals (pre-migration) or when option
             chain lookup fails. Same logic as before: use SPX price delta
             with direction sign.

        Returns:
            dict with keys:
              outcome:       'win' / 'loss' / 'scratch' / None (None = defer)
              pnl_pct:       P&L as percentage (rounded 2dp)
              exit_premium:  option premium at resolution (0.0 for SPX path)
              method:        'option' / 'spx_fallback' / 'deferred'
        """
        direction = signal.get("direction", "NEUTRAL")
        entry_premium = float(signal.get("entry_premium", 0) or 0)
        option_strike = float(signal.get("option_strike", 0) or 0)
        option_type = (signal.get("option_type") or "").lower()

        # Path 1: option-based resolution
        if entry_premium > 0 and option_strike > 0 and option_type in ("call", "put"):
            try:
                exit_premium = await self.fetcher.lookup_option_premium(
                    option_strike, option_type
                )
            except Exception:
                logger.exception(
                    "Option lookup raised for signal #%d; falling back to SPX",
                    signal.get("id"),
                )
                exit_premium = None

            if exit_premium is not None:
                pnl_pct = ((exit_premium - entry_premium) / entry_premium) * 100.0
                if abs(pnl_pct) <= OPTION_SCRATCH_THRESHOLD_PCT:
                    outcome = "scratch"
                elif pnl_pct > 0:
                    outcome = "win"
                else:
                    outcome = "loss"
                return {
                    "outcome": outcome,
                    "pnl_pct": round(pnl_pct, 2),
                    "exit_premium": round(float(exit_premium), 2),
                    "method": "option",
                }
            # else: chain lookup failed → fall through to SPX path

        # Path 2: SPX fallback (legacy / unavailable chain)
        entry_spx = float(signal.get("spx_entry_price", 0) or 0)
        if entry_spx <= 0 or not current_spx_price:
            return {
                "outcome": None,
                "pnl_pct": 0.0,
                "exit_premium": 0.0,
                "method": "deferred",
            }

        raw_pct = ((current_spx_price - entry_spx) / entry_spx) * 100.0
        if direction == "BEAR":
            pnl_pct = -raw_pct
        elif direction == "BULL":
            pnl_pct = raw_pct
        else:
            pnl_pct = 0.0

        if abs(pnl_pct) <= SCRATCH_THRESHOLD_PCT:
            outcome = "scratch"
        elif pnl_pct > 0:
            outcome = "win"
        else:
            outcome = "loss"

        return {
            "outcome": outcome,
            "pnl_pct": round(pnl_pct, 3),
            "exit_premium": 0.0,
            "method": "spx_fallback",
        }

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
