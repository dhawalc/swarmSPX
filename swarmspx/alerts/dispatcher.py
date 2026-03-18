"""Alert dispatcher that bridges the EventBus to Telegram and Slack channels."""

from __future__ import annotations

import asyncio
import logging

from swarmspx.events import (
    EventBus,
    Event,
    TradeCardGenerated,
    ConsensusReached,
    EngineError,
)
from swarmspx.alerts.telegram import (
    format_trade_card as tg_format_card,
    format_error as tg_format_error,
    send_telegram,
)
from swarmspx.alerts.slack import (
    format_trade_card as slack_format_card,
    format_error as slack_format_error,
    send_slack,
)

logger = logging.getLogger(__name__)


class AlertDispatcher:
    """Subscribe to an EventBus and dispatch alerts to Telegram and Slack.

    Parameters
    ----------
    bus:
        The ``EventBus`` instance to listen on.
    min_confidence:
        Minimum confidence (0-100) required to send a trade-card alert.
    """

    def __init__(self, bus: EventBus, min_confidence: float = 70.0) -> None:
        self._bus = bus
        self.min_confidence = min_confidence
        self._queue = bus.subscribe()
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background listener task."""
        if self._task is None or self._task.done():
            self._task = asyncio.ensure_future(self._listen())
            logger.info(
                "AlertDispatcher started (min_confidence=%.1f%%)",
                self.min_confidence,
            )

    def stop(self) -> None:
        """Stop the background listener task."""
        if self._task and not self._task.done():
            self._task.cancel()
            logger.info("AlertDispatcher stopped")
        self._bus.unsubscribe(self._queue)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _listen(self) -> None:
        """Consume events from the bus and dispatch alerts."""
        try:
            while True:
                event: Event = await self._queue.get()
                await self._handle(event)
        except asyncio.CancelledError:
            return

    async def _handle(self, event: Event) -> None:
        """Route a single event to the appropriate alert handlers."""
        if isinstance(event, TradeCardGenerated):
            await self._on_trade_card(event)
        elif isinstance(event, EngineError):
            await self._on_error(event)

    async def _on_trade_card(self, event: TradeCardGenerated) -> None:
        card = event.trade_card
        confidence = card.get("confidence", 0)

        if confidence < self.min_confidence:
            logger.debug(
                "Trade card confidence %.1f%% below threshold %.1f%%, skipping alert",
                confidence,
                self.min_confidence,
            )
            return

        # Also alert on contrarian or herding signals regardless of confidence
        has_special = bool(card.get("contrarian_alert") or card.get("herding_warning"))
        if confidence < self.min_confidence and not has_special:
            return

        logger.info(
            "Dispatching trade alert: %s @ %.0f%% confidence",
            card.get("direction", "?"),
            confidence,
        )

        tg_text = tg_format_card(card)
        slack_payload = slack_format_card(card)

        await asyncio.gather(
            send_telegram(tg_text),
            send_slack(slack_payload),
            return_exceptions=True,
        )

    async def _on_error(self, event: EngineError) -> None:
        logger.info("Dispatching error alert: %s", event.message)
        tg_text = tg_format_error(event.message)
        slack_payload = slack_format_error(event.message)
        await asyncio.gather(
            send_telegram(tg_text),
            send_slack(slack_payload),
            return_exceptions=True,
        )
