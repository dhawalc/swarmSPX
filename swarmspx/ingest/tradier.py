"""Tradier API client for fetching SPX options chain data."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

SANDBOX_URL = "https://sandbox.tradier.com/v1"
PROD_URL = "https://api.tradier.com/v1"


class TradierClient:
    """Async client for the Tradier Options API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.api_key = api_key or os.environ.get("TRADIER_API_KEY", "")
        self.base_url = base_url or os.environ.get(
            "TRADIER_BASE_URL", SANDBOX_URL
        )
        self._headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def get_expirations(self, symbol: str = "SPX") -> list[str]:
        """Fetch available option expiration dates.

        Returns list of date strings (YYYY-MM-DD).
        """
        url = f"{self.base_url}/markets/options/expirations"
        params = {"symbol": symbol, "includeAllRoots": "true"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params, headers=self._headers)
            resp.raise_for_status()
            data = resp.json()

        expirations = data.get("expirations", {})
        if isinstance(expirations, dict):
            return expirations.get("date", [])
        return []

    async def get_options_chain(
        self,
        symbol: str = "SPX",
        expiration: Optional[str] = None,
    ) -> list[dict]:
        """Fetch options chain for a symbol and expiration.

        If expiration is None, uses today's date (0DTE).
        Returns list of raw option contract dicts.
        """
        if expiration is None:
            expiration = datetime.now().strftime("%Y-%m-%d")

        url = f"{self.base_url}/markets/options/chains"
        params = {
            "symbol": symbol,
            "expiration": expiration,
            "greeks": "true",
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params, headers=self._headers)
            resp.raise_for_status()
            data = resp.json()

        options = data.get("options", {})
        if isinstance(options, dict):
            raw = options.get("option", [])
            return raw if isinstance(raw, list) else []
        return []

    async def get_quote(self, symbol: str = "SPX") -> dict:
        """Fetch a real-time quote for a symbol."""
        url = f"{self.base_url}/markets/quotes"
        params = {"symbols": symbol}

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params, headers=self._headers)
            resp.raise_for_status()
            data = resp.json()

        quotes = data.get("quotes", {})
        if isinstance(quotes, dict):
            quote = quotes.get("quote", {})
            if isinstance(quote, list):
                return quote[0] if quote else {}
            return quote
        return {}
