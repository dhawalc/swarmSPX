"""Slack webhook alert sender for SwarmSPX trade cards."""

from __future__ import annotations

import logging
import os
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)


def _color_for_direction(direction: str) -> str:
    """Return Slack attachment color hex for a direction."""
    if direction == "BULL":
        return "#2ecc71"
    if direction == "BEAR":
        return "#e74c3c"
    return "#f1c40f"


def format_trade_card(card: dict) -> dict:
    """Build a Slack Block Kit payload for a trade card."""
    direction = card.get("direction", "NEUTRAL")
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

    emoji = ":large_green_circle:" if direction == "BULL" else ":red_circle:" if direction == "BEAR" else ":large_yellow_circle:"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} SwarmSPX: {direction} @ {confidence:.0f}% confidence",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Regime:* {regime}"},
                {"type": "mrkdwn", "text": f"*SPX:* ${spx:.2f}  |  *VIX:* {vix:.1f}"},
                {"type": "mrkdwn", "text": f"*Agreement:* {agreement:.0f}%"},
                {"type": "mrkdwn", "text": f"*Action:* {action}"},
            ],
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Instrument:* {instrument}"},
            ],
        },
    ]

    if entry is not None:
        blocks.append(
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Entry:* ~${entry:.2f}"},
                    {"type": "mrkdwn", "text": f"*Target:* ${target:.2f}"},
                    {"type": "mrkdwn", "text": f"*Stop:* ${stop:.2f}"},
                ],
            }
        )

    if rationale:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Rationale:* {rationale}"},
            }
        )

    if risk:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f":warning: *Risk:* {risk}"},
            }
        )

    alert_lines: list[str] = []
    if card.get("contrarian_alert"):
        alert_lines.append(f":rotating_light: *Contrarian Alert:* {card['contrarian_alert']}")
    if card.get("herding_warning"):
        alert_lines.append(f":rotating_light: *Herding Warning:* {card['herding_warning']}")
    if alert_lines:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(alert_lines)},
            }
        )

    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"_{timestamp}_"}],
        }
    )

    return {
        "attachments": [
            {
                "color": _color_for_direction(direction),
                "blocks": blocks,
            }
        ]
    }


def format_error(message: str) -> dict:
    """Build a Slack Block Kit payload for an engine error."""
    return {
        "attachments": [
            {
                "color": "#e74c3c",
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": ":x: SwarmSPX Engine Error",
                        },
                    },
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": message},
                    },
                ],
            }
        ]
    }


async def send_slack(payload: dict) -> bool:
    """POST a payload to the Slack webhook URL.

    Returns True on success, False otherwise.
    """
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        logger.debug("Slack webhook URL not configured, skipping")
        return False

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
            logger.info("Slack alert sent")
            return True
    except httpx.HTTPError as exc:
        logger.error("Slack send failed: %s", exc)
        return False
