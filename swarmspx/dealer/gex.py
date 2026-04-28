"""Compute dealer Gamma Exposure (GEX) from an SPX option chain.

What is GEX
-----------
Gamma exposure approximates the dollar amount of SPX that dealers must hedge
per 1% move in spot. Dealers are typically:
    - LONG calls (retail buys, dealer hedges short → buys SPX as price rises)
    - SHORT puts (retail sells/buys puts, dealer net short → sells SPX as price falls)

Net positive GEX → dealers dampen volatility (mean-reverting regime).
Net negative GEX → dealers amplify volatility (trending / explosive regime).

Formula (per strike):
    gamma_exposure = open_interest × gamma × multiplier × spot² × 0.01

    The 0.01 converts the per-1%-move convention. Multiplier=100 for SPX.
    Calls contribute POSITIVE; puts contribute NEGATIVE (sign convention used
    by SpotGamma / SqueezeMetrics).

Aggregates exposed:
    net_gex            — sum across all strikes
    gamma_flip_strike  — strike where cumulative GEX crosses zero
    call_wall          — strike with the largest positive GEX (resistance)
    put_wall           — strike with the largest negative GEX (support)
    regime             — "positive_gamma" / "negative_gamma" / "neutral"

Why in-house instead of $199/mo SpotGamma:
    The math is well-known (SqueezeMetrics whitepaper, Cem Karsan's tweets).
    The only edge SpotGamma has is being 50ms faster — irrelevant at retail
    speed. Free CBOE OI + Schwab/Tradier real-time Greeks → same numbers.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from swarmspx.ingest.options import OptionContract

# SPX options multiplier (1 contract = 100 × index)
SPX_MULTIPLIER = 100.0

# Threshold (in $ of net GEX) below which we call the regime "neutral"
NEUTRAL_GEX_THRESHOLD = 0.5e9  # $500M


@dataclass
class StrikeGEX:
    """GEX summary at a single strike."""
    strike: float
    call_gex: float
    put_gex: float
    net_gex: float
    call_oi: int
    put_oi: int


@dataclass
class GEXSnapshot:
    """Aggregate GEX picture for one option chain at a point in time."""

    spx_price: float
    net_gex: float                       # $ exposure (e.g. 1.2e9 = +$1.2B)
    regime: str                          # "positive_gamma" / "negative_gamma" / "neutral"
    gamma_flip_strike: Optional[float]   # strike where cumulative GEX crosses 0
    call_wall: Optional[float]           # strike with max positive single-strike GEX
    call_wall_gex: float
    put_wall: Optional[float]            # strike with max negative single-strike GEX
    put_wall_gex: float
    by_strike: list[StrikeGEX] = field(default_factory=list)

    def to_prompt_block(self) -> str:
        """Render a compact block for injection into agent prompts."""
        lines = [
            "DEALER POSITIONING (computed in-house from chain OI + Greeks):",
            f"  Net GEX: ${self.net_gex / 1e9:+.2f}B → {self.regime.upper()}",
        ]
        if self.gamma_flip_strike:
            lines.append(
                f"  Gamma flip: {self.gamma_flip_strike:.0f} "
                f"(above = MM dampen / below = MM amplify)"
            )
        if self.call_wall:
            lines.append(
                f"  Call wall (resistance): {self.call_wall:.0f}  "
                f"(${self.call_wall_gex / 1e9:.2f}B)"
            )
        if self.put_wall:
            lines.append(
                f"  Put wall (support):     {self.put_wall:.0f}  "
                f"(${abs(self.put_wall_gex) / 1e9:.2f}B)"
            )
        return "\n".join(lines)


def compute_gex(
    contracts: list[OptionContract],
    spx_price: float,
    multiplier: float = SPX_MULTIPLIER,
) -> Optional[GEXSnapshot]:
    """Build a GEXSnapshot from an option chain.

    Args:
        contracts:  Parsed option chain (must include open_interest + gamma).
        spx_price:  Current SPX price (used in the formula and for ordering).
        multiplier: Index multiplier — 100 for SPX.

    Returns:
        GEXSnapshot, or None if the chain is empty / unusable.
    """
    if not contracts or spx_price <= 0:
        return None

    spot_sq = spx_price * spx_price
    factor = multiplier * spot_sq * 0.01

    call_gex_by_strike: dict[float, float] = defaultdict(float)
    put_gex_by_strike: dict[float, float] = defaultdict(float)
    call_oi_by_strike: dict[float, int] = defaultdict(int)
    put_oi_by_strike: dict[float, int] = defaultdict(int)

    for c in contracts:
        if c.gamma == 0 or c.open_interest <= 0:
            continue
        strike = float(c.strike)
        gex = c.open_interest * c.gamma * factor
        if c.option_type == "call":
            call_gex_by_strike[strike] += gex
            call_oi_by_strike[strike] += c.open_interest
        elif c.option_type == "put":
            # Sign convention: puts contribute NEGATIVE GEX
            put_gex_by_strike[strike] -= gex
            put_oi_by_strike[strike] += c.open_interest

    if not call_gex_by_strike and not put_gex_by_strike:
        return None

    all_strikes = sorted(set(call_gex_by_strike) | set(put_gex_by_strike))
    by_strike: list[StrikeGEX] = []
    for k in all_strikes:
        cg = call_gex_by_strike.get(k, 0.0)
        pg = put_gex_by_strike.get(k, 0.0)
        by_strike.append(StrikeGEX(
            strike=k,
            call_gex=round(cg, 2),
            put_gex=round(pg, 2),
            net_gex=round(cg + pg, 2),
            call_oi=call_oi_by_strike.get(k, 0),
            put_oi=put_oi_by_strike.get(k, 0),
        ))

    net_gex = sum(s.net_gex for s in by_strike)

    if abs(net_gex) < NEUTRAL_GEX_THRESHOLD:
        regime = "neutral"
    elif net_gex > 0:
        regime = "positive_gamma"
    else:
        regime = "negative_gamma"

    call_walls = [s for s in by_strike if s.net_gex > 0]
    put_walls = [s for s in by_strike if s.net_gex < 0]
    call_wall = max(call_walls, key=lambda s: s.net_gex) if call_walls else None
    put_wall = min(put_walls, key=lambda s: s.net_gex) if put_walls else None

    flip = _find_gamma_flip(by_strike)

    return GEXSnapshot(
        spx_price=spx_price,
        net_gex=round(net_gex, 2),
        regime=regime,
        gamma_flip_strike=flip,
        call_wall=call_wall.strike if call_wall else None,
        call_wall_gex=call_wall.net_gex if call_wall else 0.0,
        put_wall=put_wall.strike if put_wall else None,
        put_wall_gex=put_wall.net_gex if put_wall else 0.0,
        by_strike=by_strike,
    )


def _find_gamma_flip(by_strike: list[StrikeGEX]) -> Optional[float]:
    """Find the strike where cumulative GEX crosses zero (sorted asc).

    Standard SqueezeMetrics method: walk strikes ascending, accumulate net
    GEX. The crossing point — where cumulative changes sign — is the flip
    level. Below it dealers are short gamma (amplify); above, long gamma.

    Linear interpolation gives a sub-strike estimate. If no crossing exists
    (one-sided chain), return None.
    """
    if not by_strike:
        return None

    cum = 0.0
    prev_strike = None
    prev_cum = 0.0
    for s in by_strike:
        cum += s.net_gex
        if prev_strike is not None and (prev_cum * cum < 0):
            if cum != prev_cum:
                t = -prev_cum / (cum - prev_cum)
                return round(prev_strike + t * (s.strike - prev_strike), 2)
            return s.strike
        prev_strike = s.strike
        prev_cum = cum

    return None
