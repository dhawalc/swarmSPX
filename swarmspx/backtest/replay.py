"""Event-driven backtester scaffold (replaces the synthetic Monte Carlo).

War room verdict (review H1): the existing `backtest/engine.py` runs synthetic
agent accuracies through ELO and "discovers" them — circular. This module is
the honest replacement. It replays REAL historical ticks/bars through the
SAME code path the live engine uses, applies a realistic slippage model, and
produces an honest Sharpe.

Status: SCAFFOLD. The structure is complete; the historical-data ingest path
needs Polygon.io (or similar) wiring before it can produce numbers.

Architecture
------------

    historical_events (Parquet)
            │
            ▼
        EventReplayer            ← yields events in t_exchange order
            │
            ▼
        SimClock                 ← gates "available_time" PIT-correctly
            │
            ▼
        Same engine code path    ← TradingPit, ConsensusExtractor, etc.
            │
            ▼
        SimulatedExchange        ← SlippageModel: half-spread + impact + queue
            │
            ▼
        Backtest ledger          ← per-decision audit + outcome resolution
            │
            ▼
        BacktestResult           ← Sharpe, Sortino, MaxDD, Calmar, slippage

Design constraints (non-negotiable):
    - Point-in-time correctness: features filtered by available_time.
    - Same code path as live: agent simulation / consensus / strategy NOT
      mocked. Bugs in prod are bugs in backtest.
    - Realistic fills: limit orders subject to queue; market orders pay
      half-spread + impact for size > top-of-book.
    - Walk-forward: caller supplies train + test windows.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator, Optional, Protocol

logger = logging.getLogger(__name__)


# ── Events ────────────────────────────────────────────────────────────────────

@dataclass
class MarketEvent:
    """A single tick / quote / bar event from the historical feed."""
    ts_exchange: datetime
    ts_arrival: datetime
    event_type: str                # 'tick' / 'minute_bar' / 'option_chain'
    spx_price: float
    spx_bid: float = 0.0
    spx_ask: float = 0.0
    payload: dict = field(default_factory=dict)


# ── Replayer ──────────────────────────────────────────────────────────────────

class EventReplayer:
    """Yield historical MarketEvents in t_exchange order from Parquet.

    Lazily streams — does NOT load everything into memory.
    """

    def __init__(self, parquet_path: str):
        self.path = Path(parquet_path)

    def stream(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        spx_multiplier: float = 10.0,
    ) -> Iterator[MarketEvent]:
        """Yield MarketEvents from a 1m bar Parquet file (D2DT-format).

        Schema expected: DatetimeIndex (UTC tz-aware) + columns
        ``open, high, low, close, volume, vwap``. Each minute bar emits
        one ``minute_bar`` event with t_exchange = bar timestamp.

        Args:
            start, end: optional filters (inclusive).
            spx_multiplier: SPY → SPX-equivalent multiplier (~10×). For
                            actual SPX bars pass 1.0.

        Compatible with /home/dhawal/D2DT/backend/data/minute_cache/SPY_1m_*.parquet.
        """
        import pandas as pd

        if not self.path.exists():
            raise FileNotFoundError(f"Parquet not found: {self.path}")

        df = pd.read_parquet(self.path)
        if start is not None:
            df = df[df.index >= start] if df.index.name else df[df.index >= start]
        if end is not None:
            df = df[df.index <= end]

        for ts, row in df.iterrows():
            close_px = float(row["close"]) * spx_multiplier
            yield MarketEvent(
                ts_exchange=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                ts_arrival=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                event_type="minute_bar",
                spx_price=close_px,
                spx_bid=float(row["low"]) * spx_multiplier,
                spx_ask=float(row["high"]) * spx_multiplier,
                payload={
                    "open": float(row["open"]) * spx_multiplier,
                    "close": close_px,
                    "volume": int(row["volume"]),
                    "vwap": float(row["vwap"]) * spx_multiplier if "vwap" in df.columns else close_px,
                },
            )


# ── Simulation clock ──────────────────────────────────────────────────────────

class SimClock:
    """Advances along the historical event stream.

    Holds the current sim_time (= ts_arrival of the last event). Feature
    lookups must filter `available_time <= sim_time` to honor PIT correctness.
    """

    def __init__(self, t0: datetime):
        self.t0 = t0
        self._now: datetime = t0

    def advance_to(self, ts: datetime) -> None:
        """Move the clock forward (never backward)."""
        if ts < self._now:
            raise ValueError(f"SimClock cannot rewind: {self._now} → {ts}")
        self._now = ts

    @property
    def now(self) -> datetime:
        return self._now


# ── Fill model ────────────────────────────────────────────────────────────────

@dataclass
class FillRequest:
    side: str                  # 'BUY' or 'SELL'
    quantity: int
    order_type: str            # 'MKT' or 'LMT'
    limit_price: Optional[float] = None
    arrival_ts: Optional[datetime] = None


@dataclass
class FillResult:
    filled: bool
    fill_price: float = 0.0
    fill_quantity: int = 0
    slippage_bps: float = 0.0


class SlippageModel(Protocol):
    """Interface — every backtest swaps in its own model."""
    def simulate_fill(self, req: FillRequest, book: dict) -> FillResult: ...


class HalfSpreadPlusImpactSlippage:
    """Realistic baseline:
        - MKT pays half-spread + linear impact for size > top-of-book qty.
        - LMT fills probabilistically when limit price beats best ask (buy)
          or best bid (sell). v1 has no queue-position model.
    """

    def __init__(self, impact_per_lot_bps: float = 0.5):
        self.impact_per_lot_bps = float(impact_per_lot_bps)

    def simulate_fill(self, req: FillRequest, book: dict) -> FillResult:
        bid = float(book.get("bid", 0.0))
        ask = float(book.get("ask", 0.0))
        if bid <= 0 or ask <= 0:
            return FillResult(filled=False)
        mid = (bid + ask) / 2.0
        spread = ask - bid

        if req.order_type == "MKT":
            half_spread = spread / 2.0
            impact_bps = self.impact_per_lot_bps * max(0, req.quantity - 1)
            impact_price = mid * (impact_bps / 10_000.0)
            if req.side == "BUY":
                fill_price = mid + half_spread + impact_price
            else:
                fill_price = mid - half_spread - impact_price
            slippage_bps = abs(fill_price - mid) / mid * 10_000 if mid else 0.0
            return FillResult(
                filled=True,
                fill_price=round(fill_price, 4),
                fill_quantity=req.quantity,
                slippage_bps=round(slippage_bps, 2),
            )

        if req.order_type == "LMT" and req.limit_price is not None:
            crosses = (req.side == "BUY" and req.limit_price >= ask) or \
                      (req.side == "SELL" and req.limit_price <= bid)
            if crosses:
                fill_price = req.limit_price
                slippage_bps = abs(fill_price - mid) / mid * 10_000 if mid else 0.0
                return FillResult(
                    filled=True,
                    fill_price=round(fill_price, 4),
                    fill_quantity=req.quantity,
                    slippage_bps=round(slippage_bps, 2),
                )

        return FillResult(filled=False)


# ── Result aggregation ───────────────────────────────────────────────────────

@dataclass
class TradeRecord:
    """One round-trip trade in the backtest ledger."""
    signal_id: int
    open_ts: datetime
    close_ts: datetime
    direction: str
    entry_premium: float
    exit_premium: float
    contracts: int
    pnl_usd: float
    pnl_pct: float
    slippage_bps: float
    method: str                # 'option' / 'spx_fallback'


@dataclass
class BacktestResult:
    """Headline metrics for a single backtest run."""
    n_trades: int
    n_wins: int
    n_losses: int
    win_rate: float
    avg_win_pct: float
    avg_loss_pct: float
    total_pnl_usd: float
    sharpe: float
    sortino: float
    max_drawdown_pct: float
    calmar: float
    avg_slippage_bps: float
    trades: list[TradeRecord] = field(default_factory=list)


def compute_metrics(trades: list[TradeRecord]) -> BacktestResult:
    """Aggregate per-trade records into headline metrics.

    Sharpe is per-trade (NOT annualised — frequency varies). Sortino uses
    only negative returns for downside deviation. Max-drawdown is on
    cumulative P&L (% of peak).
    """
    n = len(trades)
    if n == 0:
        return BacktestResult(
            n_trades=0, n_wins=0, n_losses=0, win_rate=0.0,
            avg_win_pct=0.0, avg_loss_pct=0.0, total_pnl_usd=0.0,
            sharpe=0.0, sortino=0.0, max_drawdown_pct=0.0, calmar=0.0,
            avg_slippage_bps=0.0, trades=[],
        )

    wins = [t for t in trades if t.pnl_pct > 0]
    losses = [t for t in trades if t.pnl_pct < 0]

    avg_win = sum(t.pnl_pct for t in wins) / len(wins) if wins else 0.0
    avg_loss = sum(t.pnl_pct for t in losses) / len(losses) if losses else 0.0

    returns = [t.pnl_pct / 100.0 for t in trades]
    mean_r = sum(returns) / n
    std_r = math.sqrt(sum((r - mean_r) ** 2 for r in returns) / n) if n > 1 else 0.0
    sharpe = (mean_r / std_r) if std_r > 0 else 0.0

    downside = [r for r in returns if r < 0]
    if downside:
        std_down = math.sqrt(sum(r * r for r in downside) / len(downside))
        sortino = (mean_r / std_down) if std_down > 0 else 0.0
    else:
        sortino = 0.0

    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in returns:
        cum += r
        if cum > peak:
            peak = cum
        dd = (cum - peak)
        if dd < max_dd:
            max_dd = dd
    max_dd_pct = abs(max_dd) * 100.0

    total_pnl_usd = sum(t.pnl_usd for t in trades)
    avg_slippage = sum(t.slippage_bps for t in trades) / n

    calmar = (mean_r * n / max_dd_pct * 100) if max_dd_pct > 0 else 0.0

    return BacktestResult(
        n_trades=n,
        n_wins=len(wins),
        n_losses=len(losses),
        win_rate=round(len(wins) / n * 100, 2) if n else 0.0,
        avg_win_pct=round(avg_win, 2),
        avg_loss_pct=round(avg_loss, 2),
        total_pnl_usd=round(total_pnl_usd, 2),
        sharpe=round(sharpe, 3),
        sortino=round(sortino, 3),
        max_drawdown_pct=round(max_dd_pct, 2),
        calmar=round(calmar, 3),
        avg_slippage_bps=round(avg_slippage, 2),
        trades=trades,
    )


# ── Walk-forward orchestration ────────────────────────────────────────────────

@dataclass
class WalkForwardWindow:
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime


def generate_walk_forward_windows(
    start: datetime,
    end: datetime,
    train_days: int = 365,
    test_days: int = 90,
    step_days: int = 90,
) -> list[WalkForwardWindow]:
    """Generate non-overlapping test windows with rolling training periods.

    Standard López de Prado pattern:
      - First window: train [start, start+train_days], test next test_days
      - Roll forward by step_days; repeat until end.
    """
    windows: list[WalkForwardWindow] = []
    train_start = start
    while True:
        train_end = train_start + timedelta(days=train_days)
        test_start = train_end
        test_end = test_start + timedelta(days=test_days)
        if test_end > end:
            break
        windows.append(WalkForwardWindow(
            train_start=train_start,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
        ))
        train_start = train_start + timedelta(days=step_days)
    return windows
