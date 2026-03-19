"""Market data fetcher — Schwab primary, yfinance fallback.

Data source priority:
1. Schwab API (real-time L1, 120 req/min) — requires token
2. yfinance (delayed, free) — fallback when Schwab unavailable

Options chain priority:
1. Schwab ($SPX chain with Greeks)
2. Tradier (sandbox/production)
"""

import logging
from datetime import datetime
from typing import Optional

from swarmspx.ingest.schwab import SchwabClient
from swarmspx.ingest.tradier import TradierClient
from swarmspx.ingest.options import OptionContract, OptionsSnapshot

logger = logging.getLogger(__name__)


class MarketDataFetcher:
    """Fetches SPX, VIX, and options chain data."""

    def __init__(self, spx_ticker="^GSPC", vix_ticker="^VIX"):
        self.spx_ticker = spx_ticker
        self.vix_ticker = vix_ticker
        self.schwab = SchwabClient()
        self.tradier = TradierClient()
        self._options_snapshot: Optional[OptionsSnapshot] = None

    def get_snapshot(self) -> dict:
        """Get current market state snapshot.

        Tries Schwab first, falls back to yfinance.
        """
        # Try Schwab first (real-time)
        if self.schwab.is_configured:
            try:
                snapshot = self._get_schwab_snapshot()
                if snapshot.get("spx_price"):
                    logger.info("Market data from Schwab: SPX %.2f VIX %.2f",
                               snapshot["spx_price"], snapshot.get("vix_level", 0))
                    return snapshot
            except Exception as e:
                logger.warning("Schwab snapshot failed, falling back to yfinance: %s", e)

        # Fallback to yfinance
        return self._get_yfinance_snapshot()

    def _get_schwab_snapshot(self) -> dict:
        """Build market snapshot from Schwab real-time data."""
        quotes = self.schwab.get_spx_vix()
        if not quotes.get("spx_price"):
            return self._empty_snapshot()

        spx_price = quotes["spx_price"]
        spx_open = quotes.get("spx_open", spx_price)
        spx_change_pct = quotes.get("spx_change_pct", 0)
        vix_level = quotes.get("vix_level", 15.0)
        vix_change = quotes.get("vix_change", 0)

        # VWAP approximation from open/high/low/close
        spx_high = quotes.get("spx_high", spx_price)
        spx_low = quotes.get("spx_low", spx_price)
        vwap = (spx_high + spx_low + spx_price) / 3  # typical price approx

        regime = self._classify_regime(vix_level, spx_change_pct)

        # Get ES futures for pre-market context
        futures = self.schwab.get_futures()

        snapshot = {
            "timestamp": datetime.now().isoformat(),
            "spx_price": spx_price,
            "spx_open": spx_open,
            "spx_change_pct": round(spx_change_pct, 3),
            "spx_high": spx_high,
            "spx_low": spx_low,
            "spx_vwap": round(vwap, 2),
            "spx_vwap_distance_pct": round(((spx_price - vwap) / vwap) * 100, 3) if vwap else 0,
            "vix_level": vix_level,
            "vix_change": vix_change,
            "put_call_ratio": 1.0,  # overridden by enrich_with_options()
            "market_regime": regime,
            "is_market_hours": self._is_market_hours(),
            "data_source": "schwab",
        }

        # Add futures data if available
        if futures:
            snapshot.update(futures)

        return snapshot

    def _get_yfinance_snapshot(self) -> dict:
        """Fallback: build market snapshot from yfinance (delayed)."""
        try:
            import yfinance as yf
            import pandas as pd

            spx = yf.Ticker(self.spx_ticker)
            vix = yf.Ticker(self.vix_ticker)

            spx_hist = spx.history(period="5d", interval="1m")
            vix_hist = vix.history(period="2d", interval="1m")

            if spx_hist.empty:
                return self._empty_snapshot()

            spx_price = float(spx_hist["Close"].iloc[-1])
            spx_open = float(spx_hist["Open"].iloc[0]) if len(spx_hist) > 0 else spx_price
            spx_change_pct = ((spx_price - spx_open) / spx_open) * 100

            today = datetime.now().date()
            today_bars = spx_hist[spx_hist.index.date == today] if not spx_hist.empty else spx_hist
            vwap = self._calculate_vwap(today_bars) if not today_bars.empty else spx_price

            vix_level = float(vix_hist["Close"].iloc[-1]) if not vix_hist.empty else 15.0
            vix_prev = float(vix_hist["Close"].iloc[-2]) if len(vix_hist) > 1 else vix_level
            vix_change = vix_level - vix_prev

            regime = self._classify_regime(vix_level, spx_change_pct)

            return {
                "timestamp": datetime.now().isoformat(),
                "spx_price": round(spx_price, 2),
                "spx_open": round(spx_open, 2),
                "spx_change_pct": round(spx_change_pct, 3),
                "spx_vwap": round(vwap, 2),
                "spx_vwap_distance_pct": round(((spx_price - vwap) / vwap) * 100, 3),
                "vix_level": round(vix_level, 2),
                "vix_change": round(vix_change, 2),
                "put_call_ratio": 1.0,
                "market_regime": regime,
                "is_market_hours": self._is_market_hours(),
                "data_source": "yfinance",
            }
        except Exception as e:
            return {**self._empty_snapshot(), "error": str(e)}

    async def enrich_with_options(self, snapshot: dict) -> dict:
        """Add live options chain data to a market snapshot.

        Priority: Schwab chain → Tradier chain → none.
        """
        spx_price = snapshot.get("spx_price", 0.0)
        if not spx_price:
            return snapshot

        # Try Schwab options chain first
        if self.schwab.is_configured:
            try:
                raw_chain = self.schwab.get_option_chain("$SPX", strike_count=40)
                if raw_chain:
                    contracts = [OptionContract.from_raw(r) for r in raw_chain]
                    self._apply_options(snapshot, contracts, spx_price, "schwab")
                    logger.info("Options chain from Schwab: %d contracts", len(contracts))
                    return snapshot
            except Exception as e:
                logger.warning("Schwab options failed, trying Tradier: %s", e)

        # Fallback to Tradier
        if self.tradier.is_configured:
            try:
                raw_chain = await self.tradier.get_options_chain()
                if raw_chain:
                    contracts = [OptionContract.from_raw(r) for r in raw_chain]
                    self._apply_options(snapshot, contracts, spx_price, "tradier")
                    logger.info("Options chain from Tradier: %d contracts", len(contracts))
                    return snapshot
            except Exception as e:
                logger.warning("Tradier options failed: %s", e)

        return snapshot

    def _apply_options(self, snapshot: dict, contracts: list, spx_price: float, source: str):
        """Apply parsed options contracts to the snapshot."""
        opts = OptionsSnapshot.from_chain(contracts, spx_price)
        self._options_snapshot = opts

        snapshot["put_call_ratio"] = opts.put_call_ratio
        snapshot["atm_strike"] = opts.atm_strike
        snapshot["atm_iv"] = opts.atm_iv
        snapshot["options_source"] = source

        near_atm = sorted(contracts, key=lambda c: abs(c.strike - spx_price))[:10]
        snapshot["options_chain"] = [
            {
                "strike": c.strike,
                "type": c.option_type,
                "bid": c.bid,
                "ask": c.ask,
                "delta": round(c.delta, 3),
                "gamma": round(c.gamma, 4),
                "theta": round(c.theta, 3),
                "vega": round(c.vega, 3),
                "iv": c.iv,
                "volume": c.volume,
            }
            for c in near_atm
        ]

    @staticmethod
    def _calculate_vwap(bars) -> float:
        if bars.empty:
            return 0.0
        typical_price = (bars["High"] + bars["Low"] + bars["Close"]) / 3
        vwap = (typical_price * bars["Volume"]).cumsum() / bars["Volume"].cumsum()
        return float(vwap.iloc[-1])

    @staticmethod
    def _classify_regime(vix: float, change_pct: float) -> str:
        if vix < 15:
            return "low_vol_grind" if abs(change_pct) < 0.5 else "low_vol_trending"
        elif vix < 20:
            return "normal_vol"
        elif vix < 25:
            return "elevated_vol"
        else:
            return "high_vol_panic"

    @staticmethod
    def _is_market_hours() -> bool:
        now = datetime.now()
        return 930 <= now.hour * 100 + now.minute <= 1600

    @staticmethod
    def _empty_snapshot() -> dict:
        return {
            "timestamp": datetime.now().isoformat(),
            "spx_price": 0.0,
            "spx_open": 0.0,
            "spx_change_pct": 0.0,
            "spx_vwap": 0.0,
            "spx_vwap_distance_pct": 0.0,
            "vix_level": 0.0,
            "vix_change": 0.0,
            "put_call_ratio": 1.0,
            "market_regime": "unknown",
            "is_market_hours": False,
            "data_source": "none",
        }
