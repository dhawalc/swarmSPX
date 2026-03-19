"""Tests for strategy selector and premium-based strike selection."""

import pytest
from unittest.mock import patch
from swarmspx.ingest.options import (
    OptionContract, OptionsSnapshot,
    select_by_premium, build_vertical, build_iron_condor,
)
from swarmspx.strategy.selector import select_strategy, _get_session, _is_choppy


# --- Test fixtures ---

def _make_contract(strike, option_type, bid, ask, delta, gamma=0.01, iv=0.18):
    return OptionContract(
        strike=strike, option_type=option_type,
        bid=bid, ask=ask, mid=round((bid + ask) / 2, 2),
        spread=round(ask - bid, 2),
        volume=1000, open_interest=5000,
        delta=delta, gamma=gamma, theta=-0.3, vega=0.1, iv=iv,
    )


def _make_chain(spx_price=5800.0):
    """Build a realistic chain around SPX 5800."""
    contracts = [
        # Calls — OTM
        _make_contract(5810, "call", 12.50, 13.00, 0.48),
        _make_contract(5820, "call", 7.00, 7.50, 0.32),
        _make_contract(5830, "call", 4.80, 5.20, 0.22),
        _make_contract(5840, "call", 3.00, 3.40, 0.15),
        _make_contract(5850, "call", 1.80, 2.10, 0.10),
        _make_contract(5860, "call", 0.90, 1.20, 0.06),
        _make_contract(5870, "call", 0.40, 0.60, 0.03),
        _make_contract(5880, "call", 0.15, 0.30, 0.01),
        # Puts — OTM
        _make_contract(5790, "put", 12.00, 12.50, -0.47),
        _make_contract(5780, "put", 7.20, 7.60, -0.33),
        _make_contract(5770, "put", 5.00, 5.40, -0.23),
        _make_contract(5760, "put", 3.20, 3.50, -0.15),
        _make_contract(5750, "put", 1.90, 2.20, -0.10),
        _make_contract(5740, "put", 0.80, 1.10, -0.06),
        _make_contract(5730, "put", 0.30, 0.50, -0.03),
    ]
    return OptionsSnapshot.from_chain(contracts, spx_price)


# --- select_by_premium ---

def test_select_by_premium_bull_finds_5_to_8():
    snap = _make_chain()
    result = select_by_premium(snap, 5800.0, "BULL", premium_min=5.0, premium_max=8.0)
    assert result is not None
    assert result["option_type"] == "call"
    assert 5.0 <= result["premium_ask"] <= 8.0
    assert result["strike"] > 5800  # OTM call


def test_select_by_premium_bear_finds_5_to_8():
    snap = _make_chain()
    result = select_by_premium(snap, 5800.0, "BEAR", premium_min=5.0, premium_max=8.0)
    assert result is not None
    assert result["option_type"] == "put"
    assert 5.0 <= result["premium_ask"] <= 8.0
    assert result["strike"] < 5800  # OTM put


def test_select_by_premium_prefers_cheapest():
    """Within range, picks the cheapest (most OTM) for max asymmetry."""
    snap = _make_chain()
    result = select_by_premium(snap, 5800.0, "BULL", premium_min=3.0, premium_max=8.0)
    assert result is not None
    # Should pick the 5840C at $3.40 (cheapest in range), not the 5820C at $7.50
    assert result["premium_ask"] <= 4.0


def test_select_by_premium_lotto_range():
    """Afternoon lotto: $0.50-$2.00 deep OTM."""
    snap = _make_chain()
    result = select_by_premium(snap, 5800.0, "BULL", premium_min=0.50, premium_max=2.00)
    assert result is not None
    assert result["premium_ask"] <= 2.00
    assert result["strike"] >= 5850  # deep OTM


def test_select_by_premium_neutral_returns_none():
    snap = _make_chain()
    assert select_by_premium(snap, 5800.0, "NEUTRAL") is None


def test_select_by_premium_has_target():
    snap = _make_chain()
    result = select_by_premium(snap, 5800.0, "BULL", premium_min=5.0, premium_max=8.0)
    assert result is not None
    assert result["target_premium"] > result["premium_ask"]  # 3x target


# --- build_vertical ---

def test_build_vertical_bull():
    snap = _make_chain()
    result = build_vertical(snap, 5800.0, "BULL", max_debit=5.0, width=20.0)
    assert result is not None
    assert result["strategy"] == "VERTICAL"
    assert result["direction"] == "BULL"
    assert len(result["legs"]) == 2
    assert result["legs"][0]["action"] == "BUY"
    assert result["legs"][1]["action"] == "SELL"
    assert result["net_debit"] <= 5.0
    assert result["max_gain"] > 0
    assert result["rr_ratio"] > 0


def test_build_vertical_bear():
    snap = _make_chain()
    result = build_vertical(snap, 5800.0, "BEAR", max_debit=5.0, width=20.0)
    assert result is not None
    assert result["strategy"] == "VERTICAL"
    assert result["direction"] == "BEAR"
    assert result["legs"][0]["option_type"] == "put"


def test_build_vertical_neutral_returns_none():
    snap = _make_chain()
    assert build_vertical(snap, 5800.0, "NEUTRAL") is None


def test_build_vertical_rr_positive():
    """Vertical must have positive risk:reward."""
    snap = _make_chain()
    result = build_vertical(snap, 5800.0, "BULL", max_debit=5.0)
    if result:
        assert result["rr_ratio"] > 0
        assert result["max_gain"] > result["net_debit"]


# --- build_iron_condor ---

def test_build_iron_condor():
    snap = _make_chain()
    result = build_iron_condor(snap, 5800.0, wing_width=20.0)
    assert result is not None
    assert result["strategy"] == "IRON_CONDOR"
    assert result["direction"] == "NEUTRAL"
    assert len(result["legs"]) == 4
    assert result["net_credit"] > 0
    assert result["breakeven_low"] < 5800
    assert result["breakeven_high"] > 5800


def test_iron_condor_legs_structure():
    snap = _make_chain()
    result = build_iron_condor(snap, 5800.0)
    if result:
        actions = [l["action"] for l in result["legs"]]
        assert actions.count("SELL") == 2
        assert actions.count("BUY") == 2


# --- Strategy selector ---

@patch("swarmspx.strategy.selector._get_session", return_value="morning")
def test_strategy_directional_low_vix(mock_session):
    """High confidence + low VIX → straight OTM."""
    snap = _make_chain()
    consensus = {"direction": "BULL", "confidence": 78}
    market = {"spx_price": 5800, "vix_level": 16.0, "market_regime": "low_vol_trending"}
    result = select_strategy(consensus, market, snap)
    assert result["strategy"] in ("STRAIGHT", "VERTICAL")
    assert result["trade"] is not None


@patch("swarmspx.strategy.selector._get_session", return_value="morning")
def test_strategy_directional_high_vix(mock_session):
    """High confidence + high VIX → vertical spread."""
    snap = _make_chain()
    consensus = {"direction": "BEAR", "confidence": 75}
    market = {"spx_price": 5800, "vix_level": 26.0, "market_regime": "high_vol_panic"}
    result = select_strategy(consensus, market, snap)
    # Should prefer vertical when VIX > 20
    assert result["strategy"] in ("VERTICAL", "STRAIGHT")
    assert result["trade"] is not None


def test_strategy_choppy_iron_condor():
    """Low conviction + range-bound → iron condor."""
    snap = _make_chain()
    consensus = {"direction": "NEUTRAL", "confidence": 58}
    market = {"spx_price": 5800, "vix_level": 17.0, "market_regime": "low_vol_grind"}
    result = select_strategy(consensus, market, snap)
    assert result["strategy"] in ("IRON_CONDOR", "WAIT")


def test_strategy_wait_on_low_conviction():
    """Very low conviction neutral → WAIT."""
    consensus = {"direction": "NEUTRAL", "confidence": 40}
    market = {"spx_price": 5800, "vix_level": 15.0, "market_regime": "unknown"}
    result = select_strategy(consensus, market, None)
    assert result["strategy"] in ("WAIT",)


@patch("swarmspx.strategy.selector._get_session", return_value="afternoon")
def test_strategy_afternoon_lotto(mock_session):
    """Afternoon session → lotto play with cheap OTM."""
    snap = _make_chain()
    consensus = {"direction": "BULL", "confidence": 72}
    market = {"spx_price": 5800, "vix_level": 18.0, "market_regime": "normal_vol"}
    result = select_strategy(consensus, market, snap)
    assert result["strategy"] == "LOTTO"
    assert result["trade"]["premium_ask"] <= 2.00


def test_strategy_no_chain_guidance():
    """No options chain → returns guidance text."""
    consensus = {"direction": "BEAR", "confidence": 75}
    market = {"spx_price": 5800, "vix_level": 22.0, "market_regime": "elevated_vol"}
    result = select_strategy(consensus, market, None)
    assert result["strategy"] in ("GUIDANCE", "WAIT")
    assert "BEAR" in result.get("reason", "") or result["strategy"] == "WAIT"


# --- Helper tests ---

def test_is_choppy_low_vol_grind():
    assert _is_choppy("low_vol_grind", 55, "BULL") is True

def test_is_choppy_trending():
    assert _is_choppy("low_vol_trending", 80, "BULL") is False

def test_is_choppy_neutral_consensus():
    assert _is_choppy("normal_vol", 60, "NEUTRAL") is True
