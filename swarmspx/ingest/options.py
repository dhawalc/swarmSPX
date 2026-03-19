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


def _contract_dict(c: OptionContract) -> dict:
    """Convert an OptionContract to a dict for trade card output."""
    return {
        "strike": c.strike,
        "option_type": c.option_type,
        "premium_bid": c.bid,
        "premium_ask": c.ask,
        "premium_mid": c.mid,
        "delta": c.delta,
        "gamma": c.gamma,
        "theta": c.theta,
        "vega": c.vega,
        "implied_vol": c.iv,
        "volume": c.volume,
        "open_interest": c.open_interest,
    }


def select_strikes(
    snapshot: OptionsSnapshot,
    spx_price: float,
    direction: str,
) -> Optional[dict]:
    """Select a recommended strike based on direction (legacy delta-based).

    BULL: OTM call near 0.30 delta
    BEAR: OTM put near -0.30 delta
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

    best = min(candidates, key=lambda c: abs(c.delta - target_delta))
    return _contract_dict(best)


def select_by_premium(
    snapshot: OptionsSnapshot,
    spx_price: float,
    direction: str,
    premium_min: float = 5.0,
    premium_max: float = 8.0,
) -> Optional[dict]:
    """Select an OTM strike by premium range (the gamma scalper's method).

    Finds OTM options where the ask falls within the target premium range.
    Prefers the cheapest option within range (more OTM = more asymmetry).
    """
    if direction == "BULL":
        candidates = [
            c for c in snapshot.contracts
            if c.option_type == "call" and c.strike > spx_price
            and c.ask >= premium_min and c.ask <= premium_max
            and c.delta > 0
        ]
    elif direction == "BEAR":
        candidates = [
            c for c in snapshot.contracts
            if c.option_type == "put" and c.strike < spx_price
            and c.ask >= premium_min and c.ask <= premium_max
            and c.delta < 0
        ]
    else:
        return None

    if not candidates:
        return None

    # Prefer cheapest (most OTM) for max asymmetry
    best = min(candidates, key=lambda c: c.ask)
    result = _contract_dict(best)
    result["target_premium"] = round(best.ask * 3, 2)  # 3x target
    return result


def build_vertical(
    snapshot: OptionsSnapshot,
    spx_price: float,
    direction: str,
    max_debit: float = 5.0,
    width: float = 20.0,
) -> Optional[dict]:
    """Build a vertical debit spread.

    BULL: buy OTM call, sell further OTM call (width apart)
    BEAR: buy OTM put, sell further OTM put (width apart)
    Max risk = net debit paid. Max gain = width - debit.
    """
    if direction == "BULL":
        option_type = "call"
        otm = [c for c in snapshot.contracts
               if c.option_type == "call" and c.strike > spx_price and c.delta > 0]
        otm.sort(key=lambda c: c.strike)
    elif direction == "BEAR":
        option_type = "put"
        otm = [c for c in snapshot.contracts
               if c.option_type == "put" and c.strike < spx_price and c.delta < 0]
        otm.sort(key=lambda c: c.strike, reverse=True)
    else:
        return None

    if len(otm) < 2:
        return None

    # Try each long leg, find a short leg ~width points away
    for long_leg in otm:
        if direction == "BULL":
            short_candidates = [c for c in otm if abs(c.strike - long_leg.strike - width) < 10 and c.strike > long_leg.strike]
        else:
            short_candidates = [c for c in otm if abs(long_leg.strike - c.strike - width) < 10 and c.strike < long_leg.strike]

        if not short_candidates:
            continue

        short_leg = min(short_candidates, key=lambda c: abs(
            (c.strike - long_leg.strike if direction == "BULL" else long_leg.strike - c.strike) - width
        ))

        net_debit = round(long_leg.ask - short_leg.bid, 2)
        if net_debit <= 0:
            continue
        if net_debit > max_debit:
            continue

        actual_width = abs(long_leg.strike - short_leg.strike)
        max_gain = round(actual_width - net_debit, 2)
        rr_ratio = round(max_gain / net_debit, 1) if net_debit > 0 else 0

        return {
            "strategy": "VERTICAL",
            "direction": direction,
            "legs": [
                {"action": "BUY", **_contract_dict(long_leg)},
                {"action": "SELL", **_contract_dict(short_leg)},
            ],
            "net_debit": net_debit,
            "max_gain": max_gain,
            "max_loss": net_debit,
            "rr_ratio": rr_ratio,
            "width": actual_width,
        }

    return None


def build_iron_condor(
    snapshot: OptionsSnapshot,
    spx_price: float,
    wing_width: float = 20.0,
    target_credit: float = 3.0,
) -> Optional[dict]:
    """Build an iron condor for range-bound / choppy markets.

    Sell OTM put + OTM call, buy wings further out.
    Profit if SPX stays between short strikes.
    """
    calls = [c for c in snapshot.contracts if c.option_type == "call" and c.strike > spx_price and c.delta > 0]
    puts = [c for c in snapshot.contracts if c.option_type == "put" and c.strike < spx_price and c.delta < 0]

    if len(calls) < 2 or len(puts) < 2:
        return None

    calls.sort(key=lambda c: c.strike)
    puts.sort(key=lambda c: c.strike, reverse=True)

    # Sell ~0.15-0.20 delta options
    short_call_candidates = [c for c in calls if 0.10 <= abs(c.delta) <= 0.25]
    short_put_candidates = [c for c in puts if 0.10 <= abs(c.delta) <= 0.25]

    if not short_call_candidates or not short_put_candidates:
        return None

    short_call = min(short_call_candidates, key=lambda c: abs(abs(c.delta) - 0.16))
    short_put = min(short_put_candidates, key=lambda c: abs(abs(c.delta) - 0.16))

    # Find wing (long) legs ~wing_width further out
    long_call_candidates = [c for c in calls if abs(c.strike - short_call.strike - wing_width) < 10 and c.strike > short_call.strike]
    long_put_candidates = [c for c in puts if abs(short_put.strike - c.strike - wing_width) < 10 and c.strike < short_put.strike]

    if not long_call_candidates or not long_put_candidates:
        return None

    long_call = min(long_call_candidates, key=lambda c: abs(c.strike - short_call.strike - wing_width))
    long_put = min(long_put_candidates, key=lambda c: abs(short_put.strike - c.strike - wing_width))

    call_credit = round(short_call.bid - long_call.ask, 2)
    put_credit = round(short_put.bid - long_put.ask, 2)
    net_credit = round(call_credit + put_credit, 2)

    if net_credit <= 0:
        return None

    call_width = abs(long_call.strike - short_call.strike)
    put_width = abs(short_put.strike - long_put.strike)
    max_risk = round(max(call_width, put_width) - net_credit, 2)

    return {
        "strategy": "IRON_CONDOR",
        "direction": "NEUTRAL",
        "legs": [
            {"action": "SELL", **_contract_dict(short_put)},
            {"action": "BUY", **_contract_dict(long_put)},
            {"action": "SELL", **_contract_dict(short_call)},
            {"action": "BUY", **_contract_dict(long_call)},
        ],
        "net_credit": net_credit,
        "max_gain": net_credit,
        "max_loss": max_risk,
        "rr_ratio": round(net_credit / max_risk, 1) if max_risk > 0 else 0,
        "breakeven_low": round(short_put.strike - net_credit, 2),
        "breakeven_high": round(short_call.strike + net_credit, 2),
    }
