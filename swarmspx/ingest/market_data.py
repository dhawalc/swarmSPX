import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional

class MarketDataFetcher:
    """Fetches SPX, VIX, and options chain data via yfinance."""

    def __init__(self, spx_ticker="^GSPC", vix_ticker="^VIX"):
        self.spx_ticker = spx_ticker
        self.vix_ticker = vix_ticker

    def get_snapshot(self) -> dict:
        """Get current market state snapshot."""
        try:
            spx = yf.Ticker(self.spx_ticker)
            vix = yf.Ticker(self.vix_ticker)

            # Get recent bars
            spx_hist = spx.history(period="5d", interval="1m")
            vix_hist = vix.history(period="2d", interval="1m")

            if spx_hist.empty:
                return self._empty_snapshot()

            spx_price = float(spx_hist["Close"].iloc[-1])
            spx_open = float(spx_hist["Open"].iloc[0]) if len(spx_hist) > 0 else spx_price
            spx_change_pct = ((spx_price - spx_open) / spx_open) * 100

            # VWAP (today's bars only)
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
                "put_call_ratio": 1.0,  # placeholder — CBOE data requires scraping
                "market_regime": regime,
                "is_market_hours": self._is_market_hours(),
            }
        except Exception as e:
            return {**self._empty_snapshot(), "error": str(e)}

    def _calculate_vwap(self, bars: pd.DataFrame) -> float:
        if bars.empty:
            return 0.0
        typical_price = (bars["High"] + bars["Low"] + bars["Close"]) / 3
        vwap = (typical_price * bars["Volume"]).cumsum() / bars["Volume"].cumsum()
        return float(vwap.iloc[-1])

    def _classify_regime(self, vix: float, change_pct: float) -> str:
        if vix < 15:
            return "low_vol_grind" if abs(change_pct) < 0.5 else "low_vol_trending"
        elif vix < 20:
            return "normal_vol"
        elif vix < 25:
            return "elevated_vol"
        else:
            return "high_vol_panic"

    def _is_market_hours(self) -> bool:
        now = datetime.now()
        # Rough check — 9:30am-4:00pm ET (adjust for timezone)
        return 930 <= now.hour * 100 + now.minute <= 1600

    def _empty_snapshot(self) -> dict:
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
        }
