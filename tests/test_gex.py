"""Tests for swarmspx.dealer.gex — DIY GEX computation."""

from swarmspx.dealer.gex import (
    NEUTRAL_GEX_THRESHOLD,
    StrikeGEX,
    _find_gamma_flip,
    compute_gex,
)
from swarmspx.ingest.options import OptionContract


def _make_contract(strike: float, opt_type: str, gamma: float, oi: int) -> OptionContract:
    """Synthetic OptionContract with only the GEX-relevant fields populated."""
    return OptionContract(
        strike=strike,
        option_type=opt_type,
        bid=1.0, ask=1.1, mid=1.05, spread=0.10,
        volume=0, open_interest=oi,
        delta=0.0, gamma=gamma, theta=0.0, vega=0.0, iv=0.0,
    )


# ── compute_gex ──────────────────────────────────────────────────────────────

def test_empty_chain_returns_none():
    assert compute_gex([], spx_price=5450.0) is None


def test_zero_spx_returns_none():
    contracts = [_make_contract(5450, "call", 0.01, 1000)]
    assert compute_gex(contracts, spx_price=0.0) is None


def test_calls_contribute_positive():
    contracts = [_make_contract(5450, "call", 0.01, 1000)]
    snap = compute_gex(contracts, spx_price=5450.0)
    assert snap is not None
    assert snap.net_gex > 0


def test_puts_contribute_negative():
    contracts = [_make_contract(5450, "put", 0.01, 1000)]
    snap = compute_gex(contracts, spx_price=5450.0)
    assert snap is not None
    assert snap.net_gex < 0


def test_zero_oi_excluded():
    contracts = [
        _make_contract(5450, "call", 0.01, 0),       # zero OI
        _make_contract(5450, "call", 0.01, 1000),
    ]
    snap = compute_gex(contracts, spx_price=5450.0)
    assert snap is not None
    assert len(snap.by_strike) == 1


def test_zero_gamma_excluded():
    contracts = [
        _make_contract(5450, "call", 0.0, 1000),     # zero gamma
        _make_contract(5500, "call", 0.01, 1000),
    ]
    snap = compute_gex(contracts, spx_price=5450.0)
    assert snap is not None
    strikes = [s.strike for s in snap.by_strike]
    assert 5450.0 not in strikes
    assert 5500.0 in strikes


def test_regime_classification_positive_gamma():
    contracts = [_make_contract(5450, "call", 0.05, 100_000)]
    snap = compute_gex(contracts, spx_price=5450.0)
    assert snap.regime == "positive_gamma"


def test_regime_classification_negative_gamma():
    contracts = [_make_contract(5450, "put", 0.05, 100_000)]
    snap = compute_gex(contracts, spx_price=5450.0)
    assert snap.regime == "negative_gamma"


def test_regime_neutral_when_below_threshold():
    contracts = [_make_contract(5450, "call", 0.001, 10)]
    snap = compute_gex(contracts, spx_price=5450.0)
    assert snap.regime == "neutral"
    assert abs(snap.net_gex) < NEUTRAL_GEX_THRESHOLD


def test_call_wall_identified():
    contracts = [
        _make_contract(5400, "call", 0.01, 100),
        _make_contract(5450, "call", 0.05, 1000),  # biggest
        _make_contract(5500, "call", 0.02, 200),
    ]
    snap = compute_gex(contracts, spx_price=5450.0)
    assert snap.call_wall == 5450.0


def test_put_wall_identified():
    contracts = [
        _make_contract(5400, "put", 0.05, 5000),  # biggest negative
        _make_contract(5350, "put", 0.02, 1000),
    ]
    snap = compute_gex(contracts, spx_price=5400.0)
    assert snap.put_wall == 5400.0


# ── gamma flip ───────────────────────────────────────────────────────────────

def test_gamma_flip_returns_none_when_one_sided():
    rows = [
        StrikeGEX(strike=5400, call_gex=1e9, put_gex=0, net_gex=1e9, call_oi=100, put_oi=0),
        StrikeGEX(strike=5500, call_gex=2e9, put_gex=0, net_gex=2e9, call_oi=200, put_oi=0),
    ]
    assert _find_gamma_flip(rows) is None


def test_gamma_flip_finds_crossing():
    rows = [
        # Cumulative starts negative, then positive — flip in [5450, 5500]
        StrikeGEX(strike=5400, call_gex=0, put_gex=-2e9, net_gex=-2e9, call_oi=0, put_oi=100),
        StrikeGEX(strike=5450, call_gex=0, put_gex=-1e9, net_gex=-1e9, call_oi=0, put_oi=50),
        StrikeGEX(strike=5500, call_gex=5e9, put_gex=0, net_gex=5e9, call_oi=200, put_oi=0),
    ]
    flip = _find_gamma_flip(rows)
    assert flip is not None
    assert 5450.0 < flip <= 5500.0


# ── prompt block ─────────────────────────────────────────────────────────────

def test_prompt_block_renders_compactly():
    contracts = [
        _make_contract(5400, "put", 0.05, 5000),
        _make_contract(5500, "call", 0.05, 5000),
    ]
    snap = compute_gex(contracts, spx_price=5450.0)
    block = snap.to_prompt_block()
    assert "DEALER POSITIONING" in block
    assert "Net GEX" in block
