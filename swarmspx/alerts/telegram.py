"""Telegram Bot alert sender for SwarmSPX trade cards."""

from __future__ import annotations

import logging
import os
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def _escape_md2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special = r"_*[]()~`>#+-=|{}.!"
    out: list[str] = []
    for ch in str(text):
        if ch in special:
            out.append(f"\\{ch}")
        else:
            out.append(ch)
    return "".join(out)


def format_trade_card(card: dict) -> str:
    """Format a trade card dict as Telegram MarkdownV2 message."""
    direction = card.get("direction", "NEUTRAL")
    emoji = "\U0001f7e2" if direction == "BULL" else "\U0001f534" if direction == "BEAR" else "\U0001f7e1"

    confidence = card.get("confidence", 0)
    agreement = card.get("agreement_pct", 0)
    action = card.get("action", "WAIT")
    instrument = card.get("instrument", "N/A")
    regime = card.get("market_regime", "unknown")
    spx = card.get("spx_price", 0)
    vix = card.get("vix_level", 0)
    rationale = card.get("rationale", "")
    risk = card.get("key_risk", "")
    timestamp = card.get("timestamp", datetime.now().isoformat())[:19]

    entry = card.get("entry_price_est")
    target = card.get("target_price")
    stop = card.get("stop_price")

    lines = [
        f"{emoji} *SwarmSPX Trade Alert*",
        "",
        f"*Direction:* {_escape_md2(direction)}  \\|  *Confidence:* {_escape_md2(f'{confidence:.0f}')}%",
        f"*Agreement:* {_escape_md2(f'{agreement:.0f}')}%  \\|  *Action:* {_escape_md2(action)}",
        "",
        f"*Instrument:* {_escape_md2(instrument)}",
        f"*Regime:* {_escape_md2(regime)}  \\|  SPX {_escape_md2(f'${spx:.2f}')}  \\|  VIX {_escape_md2(f'{vix:.1f}')}",
    ]

    if entry is not None:
        lines.append("")
        lines.append(
            f"*Entry:* {_escape_md2(f'~${entry:.2f}')}"
            f"  \\|  *Target:* {_escape_md2(f'${target:.2f}')}"
            f"  \\|  *Stop:* {_escape_md2(f'${stop:.2f}')}"
        )

    # Greeks line (from Tradier options data)
    strike = card.get("strike")
    delta = card.get("delta")
    implied_vol = card.get("implied_vol")
    premium_bid = card.get("premium_bid")
    premium_ask = card.get("premium_ask")
    if strike is not None and delta is not None:
        greeks_parts = [f"*Strike:* {_escape_md2(f'{strike:.0f}')}"]
        if premium_bid is not None and premium_ask is not None:
            greeks_parts.append(f"*Premium:* {_escape_md2(f'${premium_bid:.2f}/${premium_ask:.2f}')}")
        greeks_parts.append(f"*Delta:* {_escape_md2(f'{delta:.2f}')}")
        if implied_vol is not None:
            greeks_parts.append(f"*IV:* {_escape_md2(f'{implied_vol:.1f}%')}")
        lines.append("")
        lines.append("  \\|  ".join(greeks_parts))

    # Strategy info (from strategy selector)
    strat = card.get("selected_strategy")
    if strat and strat.get("trade"):
        s_type = strat.get("strategy", "")
        s_reason = strat.get("reason", "")
        t = strat["trade"]
        lines.append("")
        lines.append(f"\U0001f3af *Strategy:* {_escape_md2(s_type)}")

        if t.get("legs"):
            for leg in t["legs"]:
                leg_str = (
                    f"  {leg['action']} {leg['strike']:.0f}"
                    f"{'C' if leg['option_type'] == 'call' else 'P'} "
                    f"@ ${leg.get('premium_ask', leg.get('premium_bid', 0)):.2f}"
                )
                lines.append(_escape_md2(leg_str))
        if t.get("net_debit"):
            nd = t["net_debit"]
            mg = t["max_gain"]
            rr = t["rr_ratio"]
            lines.append(f"  Debit: {_escape_md2(f'${nd:.2f}')} \\| "
                         f"Max Gain: {_escape_md2(f'${mg:.2f}')} \\| "
                         f"R:R {_escape_md2(f'{rr}:1')}")
        elif t.get("net_credit"):
            nc = t["net_credit"]
            ml = t["max_loss"]
            lines.append(f"  Credit: {_escape_md2(f'${nc:.2f}')} \\| "
                         f"Max Risk: {_escape_md2(f'${ml:.2f}')}")
        elif t.get("target_premium"):
            pa = t["premium_ask"]
            tp = t["target_premium"]
            mult = tp / pa if pa > 0 else 0
            lines.append(f"  Entry: {_escape_md2(f'${pa:.2f}')} \\| "
                         f"Target: {_escape_md2(f'${tp:.2f}')} "
                         f"\\({_escape_md2(f'{mult:.0f}x')}\\)")

        if s_reason:
            lines.append(f"_{_escape_md2(s_reason[:200])}_")

    if rationale:
        lines.append("")
        lines.append(f"_{_escape_md2(rationale)}_")

    if risk:
        lines.append("")
        lines.append(f"\u26a0\ufe0f *Risk:* {_escape_md2(risk)}")

    alerts: list[str] = []
    if card.get("contrarian_alert"):
        alerts.append(f"\U0001f6a8 *Contrarian Alert:* {_escape_md2(card['contrarian_alert'])}")
    if card.get("herding_warning"):
        alerts.append(f"\U0001f6a8 *Herding Warning:* {_escape_md2(card['herding_warning'])}")
    if alerts:
        lines.append("")
        lines.extend(alerts)

    lines.append("")
    lines.append(f"_{_escape_md2(timestamp)}_")
    return "\n".join(lines)


def format_outcome(event) -> str:
    """Format an outcome resolution as Telegram MarkdownV2 message."""
    outcome = event.outcome.upper()
    pct = event.outcome_pct
    direction = event.direction

    if outcome == "WIN":
        emoji = "\u2705"
    elif outcome == "LOSS":
        emoji = "\u274c"
    else:
        emoji = "\u2796"

    return (
        f"{emoji} *Signal Resolved*\n\n"
        f"*Direction:* {_escape_md2(direction)}  \\|  "
        f"*Outcome:* {_escape_md2(outcome)}\n"
        f"*P&L:* {_escape_md2(f'{pct:+.2f}%')}\n\n"
        f"_Signal \\#{_escape_md2(str(event.signal_id))}_"
    )


def format_error(message: str) -> str:
    """Format an engine error as Telegram MarkdownV2 message."""
    return f"\u274c *SwarmSPX Engine Error*\n\n{_escape_md2(message)}"


async def send_telegram(text: str, parse_mode: str = "MarkdownV2") -> bool:
    """Send a message via the Telegram Bot API.

    Returns True on success, False otherwise.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.debug("Telegram credentials not configured, skipping")
        return False

    url = TELEGRAM_API.format(token=token)
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            logger.info("Telegram alert sent (chat_id=%s)", chat_id)
            return True
    except httpx.HTTPError as exc:
        logger.error("Telegram send failed: %s", exc)
        return False
