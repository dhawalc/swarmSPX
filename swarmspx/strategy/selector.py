"""Strategy selector — picks trade structure based on regime, VIX, confidence, and time of day.

Implements an asymmetric gamma scalping methodology:
- Morning: buy OTM at $5-$8, target 3-4x ($15-$20+)
- Afternoon: buy deep OTM at $0.50-$1.50, target 5-10x ($5-$10)
- High VIX: use vertical spreads to define risk
- Choppy/range: iron condor to collect premium
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from swarmspx.clock import get_session as _clock_get_session
from swarmspx.ingest.options import (
    OptionsSnapshot,
    select_by_premium,
    build_vertical,
    build_iron_condor,
)


def select_strategy(
    consensus: dict,
    market_context: dict,
    options_snapshot: Optional[OptionsSnapshot] = None,
) -> dict:
    """Select the optimal trade strategy and structure.

    Returns a dict with:
      strategy: STRAIGHT | VERTICAL | IRON_CONDOR | LOTTO | WAIT
      trade: the constructed trade details (legs, premiums, R:R)
      reason: why this strategy was chosen
    """
    direction = consensus.get("direction", "NEUTRAL")
    confidence = consensus.get("confidence", 0)
    vix = market_context.get("vix_level", 15.0)
    regime = market_context.get("market_regime", "unknown")
    spx_price = market_context.get("spx_price", 0)

    session = _get_session()

    # No options data — return guidance only
    if not options_snapshot or not options_snapshot.contracts:
        return _no_chain_fallback(direction, confidence, vix, regime, session)

    # WAIT conditions
    if direction == "NEUTRAL" and confidence < 55:
        return {
            "strategy": "WAIT",
            "trade": None,
            "reason": "Low conviction neutral — no clear edge. Sit on hands.",
        }

    # Choppy / range-bound — iron condor
    if _is_choppy(regime, confidence, direction):
        trade = build_iron_condor(options_snapshot, spx_price)
        if trade:
            return {
                "strategy": "IRON_CONDOR",
                "trade": trade,
                "reason": f"Choppy regime ({regime}), low directional conviction "
                          f"({confidence:.0f}%). Selling premium with defined risk.",
            }

    # Afternoon lotto (after 1pm ET)
    if session == "afternoon" and direction != "NEUTRAL":
        trade = select_by_premium(
            options_snapshot, spx_price, direction,
            premium_min=0.50, premium_max=2.00,
        )
        if trade:
            trade["target_premium"] = round(trade["premium_ask"] * 6, 2)  # 6x target
            return {
                "strategy": "LOTTO",
                "trade": trade,
                "reason": f"Afternoon session — deep OTM lotto at ${trade['premium_ask']:.2f}. "
                          f"Target 5-10x on a late-day {direction.lower()} move.",
            }

    # Directional trade — morning / midday
    if direction in ("BULL", "BEAR"):
        # High VIX → vertical spread (define risk, premium is rich)
        if vix > 20:
            trade = build_vertical(options_snapshot, spx_price, direction, max_debit=5.0)
            if trade:
                return {
                    "strategy": "VERTICAL",
                    "trade": trade,
                    "reason": f"VIX elevated ({vix:.1f}). Vertical spread caps risk at "
                              f"${trade['net_debit']:.2f}, R:R {trade['rr_ratio']}:1.",
                }

        # Normal VIX → straight OTM in the $5-$8 sweet spot
        trade = select_by_premium(
            options_snapshot, spx_price, direction,
            premium_min=4.0, premium_max=9.0,
        )
        if trade:
            return {
                "strategy": "STRAIGHT",
                "trade": trade,
                "reason": f"Directional {direction.lower()} play at ${trade['premium_ask']:.2f}. "
                          f"Target 3x+ on a trend continuation.",
            }

        # Fallback: widen premium range
        trade = select_by_premium(
            options_snapshot, spx_price, direction,
            premium_min=2.0, premium_max=12.0,
        )
        if trade:
            return {
                "strategy": "STRAIGHT",
                "trade": trade,
                "reason": f"Best available {direction.lower()} strike at ${trade['premium_ask']:.2f}.",
            }

    return {
        "strategy": "WAIT",
        "trade": None,
        "reason": "No suitable trade structure found in the chain.",
    }


def _get_session() -> str:
    """Determine trading session: morning, midday, afternoon — anchored on ET.

    Delegates to swarmspx.clock.get_session() which uses
    ZoneInfo("America/New_York"). Without ET anchoring, a UTC server would
    classify 03:30 AM ET (07:30 UTC) as the end of "morning" and afternoon
    lottos would fire before market open (review #8).
    """
    return _clock_get_session()


def _is_choppy(regime: str, confidence: float, direction: str) -> bool:
    """Determine if market conditions favor a non-directional strategy."""
    choppy_regimes = {"low_vol_grind", "normal_vol"}
    if regime in choppy_regimes and confidence < 65:
        return True
    if direction == "NEUTRAL" and confidence > 55:
        return True  # Consensus is "stay put" — sell premium
    return False


def _no_chain_fallback(
    direction: str, confidence: float, vix: float, regime: str, session: str,
) -> dict:
    """Provide strategy guidance when no options chain is available."""
    if direction == "NEUTRAL" or confidence < 55:
        return {
            "strategy": "WAIT",
            "trade": None,
            "reason": "No options chain available and low conviction. Wait.",
        }

    if session == "afternoon":
        premium_range = "$0.50-$1.50 deep OTM lotto"
        target = "5-10x"
    else:
        premium_range = "$5-$8 OTM"
        target = "3-4x"

    structure = "vertical spread" if vix > 20 else "straight"

    return {
        "strategy": "GUIDANCE",
        "trade": None,
        "reason": f"{direction} signal ({confidence:.0f}% conf). Look for {structure} "
                  f"in the {premium_range} range. Target {target}. "
                  f"VIX at {vix:.1f}, regime: {regime}.",
    }
