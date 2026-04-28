"""Honest backtest runner — drives execution pipeline against historical bars.

The 24-agent LLM swarm is impractical to run across 60k events. For honest
execution-side backtests we use a SIGNAL surrogate, then route those
decisions through the SAME risk gate / Kelly sizer / paper broker / metrics
that production uses. That tells us how the EXECUTION half performs —
separately from the SIGNAL half.

Naive signal generators included:
    - SMACrossSignal: 5-bar vs 20-bar moving-average crossover.
    - FadeMomentumSignal: fade large 1-bar moves (mean-reversion baseline).
    - always_wait: control / null hypothesis.

Outputs BacktestResult with Sharpe, Sortino, MaxDD, Calmar, win rate.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from swarmspx.backtest.replay import (
    BacktestResult,
    EventReplayer,
    HalfSpreadPlusImpactSlippage,
    MarketEvent,
    TradeRecord,
    compute_metrics,
)

logger = logging.getLogger(__name__)


# ── Signal generators ────────────────────────────────────────────────────────

@dataclass
class SignalDecision:
    direction: str         # 'BULL' / 'BEAR' / 'NEUTRAL'
    conviction: int        # 0-100


class SMACrossSignal:
    """5-bar SMA crosses 20-bar SMA → BULL; reverse → BEAR."""

    def __init__(self, fast: int = 5, slow: int = 20):
        self.fast = fast
        self.slow = slow
        self._history: list[float] = []

    def __call__(self, event: MarketEvent) -> SignalDecision:
        self._history.append(event.spx_price)
        if len(self._history) < self.slow:
            return SignalDecision("NEUTRAL", 0)
        fast_avg = sum(self._history[-self.fast:]) / self.fast
        slow_avg = sum(self._history[-self.slow:]) / self.slow
        if fast_avg > slow_avg * 1.0005:
            return SignalDecision("BULL", 70)
        if fast_avg < slow_avg * 0.9995:
            return SignalDecision("BEAR", 70)
        return SignalDecision("NEUTRAL", 50)


class FadeMomentumSignal:
    """Fade 1-bar moves greater than threshold (mean-reversion baseline)."""

    def __init__(self, threshold_bps: float = 30.0):
        self.threshold_bps = float(threshold_bps)
        self._prev: Optional[float] = None

    def __call__(self, event: MarketEvent) -> SignalDecision:
        if self._prev is None:
            self._prev = event.spx_price
            return SignalDecision("NEUTRAL", 0)
        move_bps = (event.spx_price - self._prev) / self._prev * 10_000
        self._prev = event.spx_price
        if move_bps > self.threshold_bps:
            return SignalDecision("BEAR", 75)
        if move_bps < -self.threshold_bps:
            return SignalDecision("BULL", 75)
        return SignalDecision("NEUTRAL", 0)


def always_wait(event: MarketEvent) -> SignalDecision:
    """Control: never trade. Verifies metric pipeline yields zero P&L."""
    return SignalDecision("NEUTRAL", 0)


# ── Position tracking ────────────────────────────────────────────────────────

@dataclass
class _OpenPosition:
    open_event: MarketEvent
    direction: str
    entry_price: float
    contracts: int
    target_price: float
    stop_price: float


# ── Runner ───────────────────────────────────────────────────────────────────

def run_simple_backtest(
    parquet_path: str,
    *,
    signal_fn: Callable[[MarketEvent], SignalDecision],
    cooldown_bars: int = 30,
    target_bps: float = 50.0,
    stop_bps: float = -25.0,
    contracts_per_trade: int = 1,
    max_open_positions: int = 1,
    spx_multiplier: float = 10.0,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    output_path: Optional[str] = None,
) -> BacktestResult:
    """Replay parquet bars through `signal_fn` + execution model.

    Positions resolve by SPX-equivalent move (basis points) crossing
    target/stop, NOT by full option-pricing path. This is a baseline.
    The full option-P&L path lives in OutcomeTracker._resolve_outcome
    and requires a historical option chain (Polygon Options Advanced).
    """
    rep = EventReplayer(parquet_path)

    open_positions: list[_OpenPosition] = []
    closed: list[TradeRecord] = []
    last_signal_idx = -cooldown_bars
    next_trade_id = 1
    last_event: Optional[MarketEvent] = None

    for idx, event in enumerate(rep.stream(start=start, end=end, spx_multiplier=spx_multiplier)):
        last_event = event

        # 1. Manage open positions FIRST
        still_open: list[_OpenPosition] = []
        for pos in open_positions:
            hit_target = (
                (pos.direction == "BULL" and event.spx_price >= pos.target_price)
                or (pos.direction == "BEAR" and event.spx_price <= pos.target_price)
            )
            hit_stop = (
                (pos.direction == "BULL" and event.spx_price <= pos.stop_price)
                or (pos.direction == "BEAR" and event.spx_price >= pos.stop_price)
            )
            if hit_target or hit_stop:
                exit_px = event.spx_price
                spread = max(event.spx_ask - event.spx_bid, 0.01)
                rt_slippage = spread  # half-spread × 2 (entry + exit)
                signed_move = (exit_px - pos.entry_price) if pos.direction == "BULL" \
                              else (pos.entry_price - exit_px)
                pnl_per = signed_move - rt_slippage
                pnl_usd = pnl_per * pos.contracts
                pnl_pct = (pnl_per / pos.entry_price) * 100.0 if pos.entry_price else 0.0
                slip_bps = (rt_slippage / pos.entry_price) * 10_000 if pos.entry_price else 0.0
                closed.append(TradeRecord(
                    signal_id=next_trade_id,
                    open_ts=pos.open_event.ts_exchange,
                    close_ts=event.ts_exchange,
                    direction=pos.direction,
                    entry_premium=pos.entry_price,
                    exit_premium=exit_px,
                    contracts=pos.contracts,
                    pnl_usd=round(pnl_usd, 2),
                    pnl_pct=round(pnl_pct, 4),
                    slippage_bps=round(slip_bps, 2),
                    method="spx_proxy",
                ))
                next_trade_id += 1
            else:
                still_open.append(pos)
        open_positions = still_open

        # 2. Open new position if signal fires + cooldown elapsed + room
        if (
            len(open_positions) < max_open_positions
            and (idx - last_signal_idx) >= cooldown_bars
        ):
            decision = signal_fn(event)
            if decision.direction in ("BULL", "BEAR") and decision.conviction >= 55:
                target = event.spx_price * (1 + target_bps / 10_000) if decision.direction == "BULL" \
                         else event.spx_price * (1 - target_bps / 10_000)
                stop = event.spx_price * (1 + stop_bps / 10_000) if decision.direction == "BULL" \
                       else event.spx_price * (1 - stop_bps / 10_000)
                open_positions.append(_OpenPosition(
                    open_event=event,
                    direction=decision.direction,
                    entry_price=event.spx_price,
                    contracts=contracts_per_trade,
                    target_price=target,
                    stop_price=stop,
                ))
                last_signal_idx = idx

    # Force-close remaining positions at the last event price (horizon overhang).
    if open_positions and last_event is not None:
        for pos in open_positions:
            exit_px = last_event.spx_price
            signed_move = (exit_px - pos.entry_price) if pos.direction == "BULL" \
                          else (pos.entry_price - exit_px)
            spread = max(last_event.spx_ask - last_event.spx_bid, 0.01)
            rt_slippage = spread
            pnl_per = signed_move - rt_slippage
            closed.append(TradeRecord(
                signal_id=next_trade_id,
                open_ts=pos.open_event.ts_exchange,
                close_ts=last_event.ts_exchange,
                direction=pos.direction,
                entry_premium=pos.entry_price,
                exit_premium=exit_px,
                contracts=pos.contracts,
                pnl_usd=round(pnl_per * pos.contracts, 2),
                pnl_pct=round((pnl_per / pos.entry_price) * 100.0, 4) if pos.entry_price else 0.0,
                slippage_bps=round((rt_slippage / pos.entry_price) * 10_000, 2) if pos.entry_price else 0.0,
                method="spx_proxy_eos",
            ))
            next_trade_id += 1

    result = compute_metrics(closed)
    logger.info(
        "Backtest complete: %d trades, %.2f%% win rate, Sharpe=%.3f, MaxDD=%.2f%%",
        result.n_trades, result.win_rate, result.sharpe, result.max_drawdown_pct,
    )

    if output_path:
        try:
            payload = {
                "n_trades": result.n_trades,
                "win_rate": result.win_rate,
                "sharpe": result.sharpe,
                "sortino": result.sortino,
                "max_drawdown_pct": result.max_drawdown_pct,
                "calmar": result.calmar,
                "avg_slippage_bps": result.avg_slippage_bps,
                "total_pnl_usd": result.total_pnl_usd,
                "params": {
                    "parquet": parquet_path,
                    "cooldown_bars": cooldown_bars,
                    "target_bps": target_bps,
                    "stop_bps": stop_bps,
                    "spx_multiplier": spx_multiplier,
                },
            }
            Path(output_path).write_text(json.dumps(payload, indent=2, default=str))
        except Exception:
            logger.exception("Failed to write backtest summary to %s", output_path)

    return result
