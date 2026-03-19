"""Tests for Tradier API client, options data model, and strike selection."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from swarmspx.ingest.tradier import TradierClient
from swarmspx.ingest.options import OptionContract, OptionsSnapshot, select_strikes
from swarmspx.ingest.market_data import MarketDataFetcher


# --- Sample Tradier API responses ---

SAMPLE_CHAIN_RESPONSE = {
    "options": {
        "option": [
            {
                "symbol": "SPX260318C05800",
                "strike": 5800.0,
                "option_type": "call",
                "bid": 12.50,
                "ask": 13.00,
                "volume": 1500,
                "open_interest": 3200,
                "greeks": {
                    "delta": 0.52,
                    "gamma": 0.008,
                    "theta": -0.45,
                    "vega": 0.12,
                    "mid_iv": 0.182,
                },
            },
            {
                "symbol": "SPX260318C05820",
                "strike": 5820.0,
                "option_type": "call",
                "bid": 3.20,
                "ask": 3.40,
                "volume": 800,
                "open_interest": 1100,
                "greeks": {
                    "delta": 0.30,
                    "gamma": 0.012,
                    "theta": -0.35,
                    "vega": 0.10,
                    "mid_iv": 0.145,
                },
            },
            {
                "symbol": "SPX260318C05850",
                "strike": 5850.0,
                "option_type": "call",
                "bid": 0.80,
                "ask": 1.00,
                "volume": 400,
                "open_interest": 600,
                "greeks": {
                    "delta": 0.12,
                    "gamma": 0.006,
                    "theta": -0.15,
                    "vega": 0.05,
                    "mid_iv": 0.160,
                },
            },
            {
                "symbol": "SPX260318P05780",
                "strike": 5780.0,
                "option_type": "put",
                "bid": 3.50,
                "ask": 3.80,
                "volume": 1200,
                "open_interest": 2800,
                "greeks": {
                    "delta": -0.32,
                    "gamma": 0.010,
                    "theta": -0.40,
                    "vega": 0.11,
                    "mid_iv": 0.175,
                },
            },
            {
                "symbol": "SPX260318P05760",
                "strike": 5760.0,
                "option_type": "put",
                "bid": 1.20,
                "ask": 1.40,
                "volume": 600,
                "open_interest": 900,
                "greeks": {
                    "delta": -0.15,
                    "gamma": 0.005,
                    "theta": -0.20,
                    "vega": 0.06,
                    "mid_iv": 0.190,
                },
            },
            {
                "symbol": "SPX260318P05800",
                "strike": 5800.0,
                "option_type": "put",
                "bid": 11.80,
                "ask": 12.30,
                "volume": 1800,
                "open_interest": 4100,
                "greeks": {
                    "delta": -0.48,
                    "gamma": 0.008,
                    "theta": -0.42,
                    "vega": 0.12,
                    "mid_iv": 0.180,
                },
            },
        ]
    }
}


# --- OptionContract parsing ---


def test_option_contract_from_tradier():
    """Tradier raw dict is correctly parsed into OptionContract."""
    raw = SAMPLE_CHAIN_RESPONSE["options"]["option"][0]
    c = OptionContract.from_tradier(raw)

    assert c.strike == 5800.0
    assert c.option_type == "call"
    assert c.bid == 12.50
    assert c.ask == 13.00
    assert c.mid == 12.75
    assert c.spread == 0.50
    assert c.volume == 1500
    assert c.open_interest == 3200
    assert c.delta == 0.52
    assert c.gamma == 0.008
    assert c.theta == -0.45
    assert c.vega == 0.12
    assert c.iv == 0.182


def test_option_contract_handles_missing_greeks():
    """OptionContract gracefully handles missing greeks."""
    raw = {"strike": 5800, "option_type": "call", "bid": 10, "ask": 11}
    c = OptionContract.from_tradier(raw)
    assert c.delta == 0.0
    assert c.gamma == 0.0
    assert c.iv == 0.0


def test_option_contract_handles_none_values():
    """OptionContract handles None bid/ask/volume gracefully."""
    raw = {
        "strike": 5800,
        "option_type": "put",
        "bid": None,
        "ask": None,
        "volume": None,
        "open_interest": None,
        "greeks": {"delta": -0.5, "gamma": 0.01, "theta": -0.3, "vega": 0.1, "mid_iv": None},
    }
    c = OptionContract.from_tradier(raw)
    assert c.bid == 0.0
    assert c.ask == 0.0
    assert c.volume == 0
    assert c.iv == 0.0


# --- OptionsSnapshot ---


def _build_test_contracts() -> list[OptionContract]:
    raw_chain = SAMPLE_CHAIN_RESPONSE["options"]["option"]
    return [OptionContract.from_tradier(r) for r in raw_chain]


def test_options_snapshot_from_chain():
    """OptionsSnapshot correctly aggregates chain data."""
    contracts = _build_test_contracts()
    snap = OptionsSnapshot.from_chain(contracts, spx_price=5802.0)

    assert snap.atm_strike == 5800.0
    assert snap.atm_iv > 0  # derived from ATM call IV
    assert snap.total_call_volume == 1500 + 800 + 400  # 2700
    assert snap.total_put_volume == 1200 + 600 + 1800  # 3600
    # PCR = 3600 / 2700 = 1.33
    assert snap.put_call_ratio == 1.33


def test_put_call_ratio_calculated():
    """Put/call ratio is correctly computed from call vs put volume."""
    contracts = _build_test_contracts()
    snap = OptionsSnapshot.from_chain(contracts, spx_price=5800.0)

    total_call = sum(c.volume for c in contracts if c.option_type == "call")
    total_put = sum(c.volume for c in contracts if c.option_type == "put")
    expected_pcr = round(total_put / total_call, 2)

    assert snap.put_call_ratio == expected_pcr


def test_options_snapshot_empty_chain():
    """OptionsSnapshot from empty chain returns defaults."""
    snap = OptionsSnapshot.from_chain([], spx_price=5800.0)
    assert snap.atm_strike == 0.0
    assert snap.put_call_ratio == 1.0
    assert snap.contracts == []


# --- Strike selection ---


def test_strike_selection_bull():
    """Bull strike selection finds OTM call near 0.30 delta."""
    contracts = _build_test_contracts()
    snap = OptionsSnapshot.from_chain(contracts, spx_price=5802.0)

    result = select_strikes(snap, spx_price=5802.0, direction="BULL")

    assert result is not None
    assert result["option_type"] == "call"
    assert result["strike"] == 5820.0  # 0.30 delta call
    assert result["delta"] == 0.30
    assert result["premium_bid"] == 3.20
    assert result["premium_ask"] == 3.40
    assert result["implied_vol"] == 0.145


def test_strike_selection_bear():
    """Bear strike selection finds OTM put near -0.30 delta."""
    contracts = _build_test_contracts()
    snap = OptionsSnapshot.from_chain(contracts, spx_price=5802.0)

    result = select_strikes(snap, spx_price=5802.0, direction="BEAR")

    assert result is not None
    assert result["option_type"] == "put"
    assert result["strike"] == 5780.0  # -0.32 delta put (closest to -0.30)
    assert result["delta"] == -0.32
    assert result["premium_bid"] == 3.50
    assert result["premium_ask"] == 3.80


def test_strike_selection_neutral():
    """Neutral direction returns None (no strike recommendation)."""
    contracts = _build_test_contracts()
    snap = OptionsSnapshot.from_chain(contracts, spx_price=5802.0)

    result = select_strikes(snap, spx_price=5802.0, direction="NEUTRAL")
    assert result is None


def test_strike_selection_empty_snapshot():
    """Strike selection with no contracts returns None."""
    snap = OptionsSnapshot()
    result = select_strikes(snap, spx_price=5800.0, direction="BULL")
    assert result is None


# --- TradierClient ---


@pytest.mark.asyncio
async def test_tradier_client_parses_chain():
    """TradierClient correctly parses a mock chain response."""
    client = TradierClient(api_key="test-key", base_url="https://sandbox.tradier.com/v1")

    mock_resp = MagicMock()
    mock_resp.json.return_value = SAMPLE_CHAIN_RESPONSE
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as MockClient:
        mock_instance = AsyncMock()
        mock_instance.get = AsyncMock(return_value=mock_resp)
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_instance

        chain = await client.get_options_chain(symbol="SPX", expiration="2026-03-18")

    assert len(chain) == 6
    assert chain[0]["strike"] == 5800.0
    assert chain[0]["option_type"] == "call"


@pytest.mark.asyncio
async def test_tradier_client_get_quote():
    """TradierClient parses a quote response."""
    client = TradierClient(api_key="test-key")

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "quotes": {"quote": {"last": 5802.50, "symbol": "SPX"}}
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as MockClient:
        mock_instance = AsyncMock()
        mock_instance.get = AsyncMock(return_value=mock_resp)
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_instance

        quote = await client.get_quote("SPX")

    assert quote["last"] == 5802.50


def test_tradier_is_configured():
    """TradierClient reports configured when API key is set."""
    assert TradierClient(api_key="test").is_configured is True
    assert TradierClient(api_key="").is_configured is False


# --- MarketDataFetcher options enrichment ---


@pytest.mark.asyncio
async def test_market_data_graceful_without_tradier():
    """MarketDataFetcher.enrich_with_options is a no-op without API key."""
    fetcher = MarketDataFetcher()
    fetcher.tradier = TradierClient(api_key="")  # not configured

    snapshot = {"spx_price": 5800.0, "put_call_ratio": 1.0}
    result = await fetcher.enrich_with_options(snapshot)

    assert result["put_call_ratio"] == 1.0
    assert "options_chain" not in result


@pytest.mark.asyncio
async def test_market_data_enriches_with_tradier():
    """MarketDataFetcher.enrich_with_options adds chain data when Tradier is configured."""
    fetcher = MarketDataFetcher()
    fetcher.tradier = TradierClient(api_key="test-key")

    raw_options = SAMPLE_CHAIN_RESPONSE["options"]["option"]
    fetcher.tradier.get_options_chain = AsyncMock(return_value=raw_options)

    snapshot = {"spx_price": 5802.0, "put_call_ratio": 1.0}
    result = await fetcher.enrich_with_options(snapshot)

    assert result["put_call_ratio"] != 1.0  # overridden by live PCR
    assert result["atm_strike"] == 5800.0
    assert result["atm_iv"] > 0
    assert "options_chain" in result
    assert len(result["options_chain"]) > 0
    # Verify contract structure
    c = result["options_chain"][0]
    assert "strike" in c
    assert "delta" in c
    assert "bid" in c


@pytest.mark.asyncio
async def test_market_data_handles_tradier_failure():
    """MarketDataFetcher.enrich_with_options handles Tradier errors gracefully."""
    fetcher = MarketDataFetcher()
    fetcher.tradier = TradierClient(api_key="test-key")
    fetcher.tradier.get_options_chain = AsyncMock(side_effect=Exception("API down"))

    snapshot = {"spx_price": 5800.0, "put_call_ratio": 1.0}
    result = await fetcher.enrich_with_options(snapshot)

    # Should return original snapshot unchanged
    assert result["put_call_ratio"] == 1.0
    assert "options_chain" not in result
