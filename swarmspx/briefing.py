"""Morning briefing — pre-market day outlook via Schwab data.

Runs before market open (8:00 AM ET). No full swarm debate —
lightweight regime classification + strategy recommendation + key levels.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from swarmspx.ingest.schwab import SchwabClient
from swarmspx.ingest.options import OptionContract, OptionsSnapshot
from swarmspx.ingest.market_data import MarketDataFetcher
from swarmspx.alerts.telegram import send_telegram, _escape_md2

logger = logging.getLogger(__name__)


class MorningBriefing:
    """Generates and sends a pre-market morning briefing."""

    def __init__(self, fetcher: MarketDataFetcher):
        self.fetcher = fetcher
        self.schwab = fetcher.schwab

    async def run(self) -> dict:
        """Generate and send the morning briefing. Returns the briefing dict."""
        briefing = self._gather_data()
        await self._send_telegram(briefing)
        return briefing

    def _gather_data(self) -> dict:
        """Gather pre-market data from Schwab."""
        result = {
            "timestamp": datetime.now().isoformat(),
            "type": "morning_briefing",
        }

        # SPX previous close + VIX
        quotes = self.schwab.get_spx_vix() if self.schwab.is_configured else {}
        result["spx_prev_close"] = quotes.get("spx_price", 0)
        result["vix"] = quotes.get("vix_level", 0)
        result["vix_change"] = quotes.get("vix_change", 0)

        # ES futures (overnight move)
        futures = self.schwab.get_futures() if self.schwab.is_configured else {}
        result["es_price"] = futures.get("es_price", 0)
        result["es_change_pct"] = futures.get("es_change_pct", 0)

        # Regime forecast from VIX + ES move
        vix = result["vix"]
        es_change = result["es_change_pct"]
        result["regime_forecast"] = self._forecast_regime(vix, es_change)
        result["strategy_recommendation"] = self._recommend_strategy(
            vix, es_change, result["regime_forecast"]
        )

        # Key levels from options chain (high OI)
        if self.schwab.is_configured:
            try:
                raw_chain = self.schwab.get_option_chain("$SPX", strike_count=30)
                if raw_chain:
                    contracts = [OptionContract.from_raw(r) for r in raw_chain]
                    spx = result["spx_prev_close"] or result["es_price"]
                    if spx:
                        levels = self._find_key_levels(contracts, spx)
                        result.update(levels)
            except Exception as e:
                logger.warning("Options chain for briefing failed: %s", e)

        return result

    def _forecast_regime(self, vix: float, es_change_pct: float) -> str:
        """Forecast today's regime from pre-market data."""
        if vix >= 25:
            return "HIGH_VOL_PANIC"
        elif vix >= 20:
            if abs(es_change_pct) > 0.5:
                return "ELEVATED_VOL_TRENDING"
            return "ELEVATED_VOL"
        elif vix >= 15:
            if abs(es_change_pct) > 0.3:
                return "NORMAL_TRENDING"
            return "NORMAL_RANGE"
        else:
            if abs(es_change_pct) > 0.3:
                return "LOW_VOL_TRENDING"
            return "LOW_VOL_GRIND"

    def _recommend_strategy(self, vix: float, es_change: float, regime: str) -> dict:
        """Recommend strategy type for the day."""
        if "PANIC" in regime:
            return {
                "am_strategy": "VERTICAL SPREAD (define risk, premium rich)",
                "pm_strategy": "LOTTO (deep OTM, catch reversals)",
                "avoid": "Naked straight options (VIX crush will kill you)",
                "sizing": "Half size — wide ranges, fast moves",
            }
        elif "TRENDING" in regime:
            direction = "BULL" if es_change > 0 else "BEAR"
            if vix > 20:
                return {
                    "am_strategy": f"VERTICAL {direction} (VIX elevated, cap risk)",
                    "pm_strategy": f"LOTTO {'calls' if direction == 'BULL' else 'puts'} on continuation",
                    "avoid": "Fading the trend early",
                    "sizing": "Full size on trend, reduce on counter-trend",
                }
            else:
                return {
                    "am_strategy": f"STRAIGHT {direction} ($5-$8 OTM, ride the trend)",
                    "pm_strategy": f"LOTTO {direction.lower()} if trend holds",
                    "avoid": "Iron condors (trending day will blow a wing)",
                    "sizing": "Full size",
                }
        elif "GRIND" in regime or "RANGE" in regime:
            return {
                "am_strategy": "IRON CONDOR (sell premium, range-bound)",
                "pm_strategy": "WAIT or small lotto if breakout develops",
                "avoid": "Directional bets (no trend to ride)",
                "sizing": "Small — low vol = low reward",
            }
        else:
            return {
                "am_strategy": "WAIT for first 15min, then decide",
                "pm_strategy": "Assess midday",
                "avoid": "Opening drive trades without confirmation",
                "sizing": "Start small, add on confirmation",
            }

    def _find_key_levels(self, contracts: list[OptionContract], spx_price: float) -> dict:
        """Find key support/resistance from options chain OI and volume."""
        calls = [c for c in contracts if c.option_type == "call" and c.open_interest > 0]
        puts = [c for c in contracts if c.option_type == "put" and c.open_interest > 0]

        result = {}

        # Highest OI call strike = resistance (dealers hedging)
        if calls:
            max_oi_call = max(calls, key=lambda c: c.open_interest)
            result["resistance"] = max_oi_call.strike
            result["resistance_oi"] = max_oi_call.open_interest

        # Highest OI put strike = support (dealers hedging)
        if puts:
            max_oi_put = max(puts, key=lambda c: c.open_interest)
            result["support"] = max_oi_put.strike
            result["support_oi"] = max_oi_put.open_interest

        # Highest gamma strike = "pin" level
        all_sorted = sorted(contracts, key=lambda c: abs(c.gamma), reverse=True)
        if all_sorted:
            result["gamma_pin"] = all_sorted[0].strike

        return result

    async def _send_telegram(self, briefing: dict) -> bool:
        """Format and send briefing via Telegram."""
        vix = briefing.get("vix", 0)
        es = briefing.get("es_price", 0)
        es_chg = briefing.get("es_change_pct", 0)
        spx_prev = briefing.get("spx_prev_close", 0)
        regime = briefing.get("regime_forecast", "UNKNOWN")
        strat = briefing.get("strategy_recommendation", {})

        support = briefing.get("support", 0)
        resistance = briefing.get("resistance", 0)
        gamma_pin = briefing.get("gamma_pin", 0)

        es_dir = "\U0001f7e2" if es_chg >= 0 else "\U0001f534"
        vix_emoji = "\U0001f525" if vix >= 25 else "\u26a0\ufe0f" if vix >= 20 else "\u2705"

        lines = [
            f"\U0001f4cb *SWARMSPX MORNING BRIEFING*",
            f"_{_escape_md2(datetime.now().strftime('%B %d, %Y'))}_",
            "",
            f"*OVERNIGHT:*",
            f"  SPX prev close: {_escape_md2(f'${spx_prev:.2f}')}",
            f"  {es_dir} ES futures: {_escape_md2(f'${es:.2f}')} \\({_escape_md2(f'{es_chg:+.2f}%')}\\)",
            f"  {vix_emoji} VIX: {_escape_md2(f'{vix:.1f}')}",
            "",
            f"*REGIME FORECAST:* {_escape_md2(regime)}",
            "",
            f"*PLAYBOOK:*",
            f"  AM: {_escape_md2(strat.get('am_strategy', 'TBD'))}",
            f"  PM: {_escape_md2(strat.get('pm_strategy', 'TBD'))}",
            f"  Avoid: {_escape_md2(strat.get('avoid', 'N/A'))}",
            f"  Sizing: {_escape_md2(strat.get('sizing', 'Normal'))}",
        ]

        if support or resistance:
            lines.append("")
            lines.append(f"*KEY LEVELS:*")
            if support:
                lines.append(f"  Support: {_escape_md2(f'{support:.0f}')}")
            if resistance:
                lines.append(f"  Resistance: {_escape_md2(f'{resistance:.0f}')}")
            if gamma_pin:
                lines.append(f"  Gamma pin: {_escape_md2(f'{gamma_pin:.0f}')}")

        lines.append("")
        lines.append(f"_Swarm cycles at 9:35, 11:30, 2:00, 3:45 ET_")

        text = "\n".join(lines)
        return await send_telegram(text)
