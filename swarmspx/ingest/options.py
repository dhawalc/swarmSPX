"""Options data model and strike selection logic."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class OptionContract:
    """A single option contract with Greeks."""

    strike: float
    option_type: str  # "call" or "put"
    bid: float
    ask: float
    mid: float
    spread: float
    volume: int
    open_interest: int
    delta: float
    gamma: float
    theta: float
    vega: float
    iv: float  # implied volatility

    @classmethod
    def from_tradier(cls, raw: dict) -> OptionContract:
        """Parse a Tradier API option dict into an OptionContract."""
        greeks = raw.get("greeks") or {}
        bid = raw.get("bid", 0.0) or 0.0
        ask = raw.get("ask", 0.0) or 0.0
        return cls(
            strike=float(raw.get("strike", 0)),
            option_type=raw.get("option_type", "call"),
            bid=float(bid),
            ask=float(ask),
            mid=round((bid + ask) / 2, 2) if (bid + ask) else 0.0,
            spread=round(ask - bid, 2),
            volume=int(raw.get("volume", 0) or 0),
            open_interest=int(raw.get("open_interest", 0) or 0),
            delta=float(greeks.get("delta", 0) or 0),
            gamma=float(greeks.get("gamma", 0) or 0),
            theta=float(greeks.get("theta", 0) or 0),
            vega=float(greeks.get("vega", 0) or 0),
            iv=float(greeks.get("mid_iv", 0) or greeks.get("smv_vol", 0) or 0),
        )


@dataclass
class OptionsSnapshot:
    """Aggregated view of the options chain near ATM."""

    contracts: list[OptionContract] = field(default_factory=list)
    atm_strike: float = 0.0
    atm_iv: float = 0.0
    put_call_ratio: float = 1.0
    total_call_volume: int = 0
    total_put_volume: int = 0

    @classmethod
    def from_chain(cls, contracts: list[OptionContract], spx_price: float) -> OptionsSnapshot:
        """Build a snapshot from parsed contracts."""
        if not contracts:
            return cls()

        # ATM strike = closest strike to current SPX price
        calls = [c for c in contracts if c.option_type == "call"]
        puts = [c for c in contracts if c.option_type == "put"]

        atm_strike = min(
            {c.strike for c in contracts},
            key=lambda s: abs(s - spx_price),
        ) if contracts else 0.0

        # ATM IV from the nearest call
        atm_call = next((c for c in calls if c.strike == atm_strike), None)
        atm_iv = atm_call.iv if atm_call else 0.0

        total_call_vol = sum(c.volume for c in calls)
        total_put_vol = sum(c.volume for c in puts)
        pcr = (total_put_vol / total_call_vol) if total_call_vol > 0 else 1.0

        return cls(
            contracts=contracts,
            atm_strike=atm_strike,
            atm_iv=round(atm_iv * 100, 1) if atm_iv < 1 else round(atm_iv, 1),
            put_call_ratio=round(pcr, 2),
            total_call_volume=total_call_vol,
            total_put_volume=total_put_vol,
        )


def select_strikes(
    snapshot: OptionsSnapshot,
    spx_price: float,
    direction: str,
) -> Optional[dict]:
    """Select a recommended strike based on direction.

    BULL: OTM call near 0.30 delta
    BEAR: OTM put near -0.30 delta

    Returns dict with strike details or None if no suitable contract found.
    """
    target_delta = 0.30 if direction == "BULL" else -0.30

    if direction == "BULL":
        candidates = [
            c for c in snapshot.contracts
            if c.option_type == "call" and c.strike > spx_price and c.delta > 0
        ]
    elif direction == "BEAR":
        candidates = [
            c for c in snapshot.contracts
            if c.option_type == "put" and c.strike < spx_price and c.delta < 0
        ]
    else:
        return None

    if not candidates:
        return None

    # Find contract closest to target delta
    best = min(candidates, key=lambda c: abs(c.delta - target_delta))

    return {
        "strike": best.strike,
        "option_type": best.option_type,
        "premium_bid": best.bid,
        "premium_ask": best.ask,
        "premium_mid": best.mid,
        "delta": best.delta,
        "gamma": best.gamma,
        "theta": best.theta,
        "vega": best.vega,
        "implied_vol": best.iv,
        "volume": best.volume,
        "open_interest": best.open_interest,
    }
