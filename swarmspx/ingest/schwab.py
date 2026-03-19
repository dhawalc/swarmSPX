"""Schwab API client for live SPX/VIX quotes and options chains.

Uses the schwab-py library with OAuth2 token from D2DT project.
Primary data source — replaces yfinance for real-time data.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default token path points to D2DT's saved token
DEFAULT_TOKEN_PATH = os.path.expanduser("~/D2DT/backend/data/schwab_token.json")


class SchwabClient:
    """Synchronous Schwab client for market data."""

    def __init__(self):
        self._client = None
        self._app_key = os.environ.get("SCHWAB_APP_KEY", "")
        self._secret = os.environ.get("SCHWAB_SECRET", "")
        self._token_path = os.environ.get("SCHWAB_TOKEN_PATH", DEFAULT_TOKEN_PATH)

    @property
    def is_configured(self) -> bool:
        return bool(self._app_key and self._secret and Path(self._token_path).exists())

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self.is_configured:
            return None
        try:
            from schwab.auth import client_from_token_file
            self._client = client_from_token_file(
                token_path=self._token_path,
                api_key=self._app_key,
                app_secret=self._secret,
            )
            return self._client
        except Exception as e:
            logger.error("Schwab client init failed: %s", e)
            return None

    def get_quotes(self, symbols: list[str]) -> dict[str, dict]:
        """Fetch real-time L1 quotes for multiple symbols.

        Schwab index symbols use $ prefix: $SPX, $VIX, $NDX
        Returns dict mapping symbol -> quote data.
        """
        client = self._get_client()
        if not client:
            return {}
        try:
            resp = client.get_quotes(symbols)
            if resp.status_code == 401:
                self._client = None  # force re-auth next call
                return {}
            if resp.status_code != 200:
                logger.warning("Schwab quotes returned %d", resp.status_code)
                return {}
            return resp.json()
        except Exception as e:
            logger.error("Schwab quotes error: %s", e)
            return {}

    def get_spx_vix(self) -> dict:
        """Fetch SPX and VIX quotes, return normalized dict.

        Returns dict with spx_price, spx_change_pct, spx_open, spx_high, spx_low,
        vix_level, vix_change, etc.
        """
        data = self.get_quotes(["$SPX", "$VIX"])

        result = {}

        spx = (data.get("$SPX") or {}).get("quote", {})
        if spx.get("lastPrice"):
            result["spx_price"] = round(float(spx["lastPrice"]), 2)
            result["spx_open"] = round(float(spx.get("openPrice", 0) or 0), 2)
            result["spx_high"] = round(float(spx.get("highPrice", 0) or 0), 2)
            result["spx_low"] = round(float(spx.get("lowPrice", 0) or 0), 2)
            result["spx_close_prev"] = round(float(spx.get("closePrice", 0) or 0), 2)
            result["spx_change_pct"] = round(float(spx.get("netPercentChangeInDouble", 0) or 0), 3)
            result["spx_volume"] = int(spx.get("totalVolume", 0) or 0)

        vix = (data.get("$VIX") or {}).get("quote", {})
        if vix.get("lastPrice"):
            result["vix_level"] = round(float(vix["lastPrice"]), 2)
            result["vix_change"] = round(float(vix.get("netChange", 0) or 0), 2)
            result["vix_open"] = round(float(vix.get("openPrice", 0) or 0), 2)

        return result

    def get_futures(self) -> dict:
        """Fetch ES futures for pre-market context."""
        data = self.get_quotes(["/ES"])
        es = (data.get("/ES") or {}).get("quote", {})
        if not es.get("lastPrice"):
            return {}
        return {
            "es_price": round(float(es["lastPrice"]), 2),
            "es_change_pct": round(float(es.get("netPercentChangeInDouble", 0) or 0), 3),
            "es_volume": int(es.get("totalVolume", 0) or 0),
        }

    def get_option_chain(self, symbol: str = "$SPX", strike_count: int = 30) -> list[dict]:
        """Fetch SPX options chain with Greeks.

        Returns list of raw option contract dicts normalized for OptionContract.from_schwab().
        """
        client = self._get_client()
        if not client:
            return []
        try:
            from schwab.client import Client
            resp = client.get_option_chain(
                symbol,
                contract_type=Client.Options.ContractType.ALL,
                strike_count=strike_count,
            )
            if resp.status_code != 200:
                logger.warning("Schwab options chain returned %d", resp.status_code)
                return []

            data = resp.json()
            contracts = []

            # Parse callExpDateMap and putExpDateMap
            for date_map_key in ("callExpDateMap", "putExpDateMap"):
                date_map = data.get(date_map_key, {})
                for exp_date, strikes in date_map.items():
                    for strike_str, option_list in strikes.items():
                        for opt in option_list:
                            contracts.append(self._normalize_option(opt))

            return contracts
        except Exception as e:
            logger.error("Schwab options chain error: %s", e)
            return []

    @staticmethod
    def _normalize_option(opt: dict) -> dict:
        """Normalize a Schwab option to match our OptionContract.from_tradier() format."""
        return {
            "symbol": opt.get("symbol", ""),
            "strike": float(opt.get("strikePrice", 0)),
            "option_type": "call" if opt.get("putCall") == "CALL" else "put",
            "bid": float(opt.get("bid", 0) or 0),
            "ask": float(opt.get("ask", 0) or 0),
            "volume": int(opt.get("totalVolume", 0) or 0),
            "open_interest": int(opt.get("openInterest", 0) or 0),
            "greeks": {
                "delta": float(opt.get("delta", 0) or 0),
                "gamma": float(opt.get("gamma", 0) or 0),
                "theta": float(opt.get("theta", 0) or 0),
                "vega": float(opt.get("vega", 0) or 0),
                "mid_iv": float(opt.get("volatility", 0) or 0) / 100,  # Schwab returns as pct
            },
        }
