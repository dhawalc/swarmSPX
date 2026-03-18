"""Tests for the SwarmSPX alerting system."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from swarmspx.events import EventBus, TradeCardGenerated, EngineError
from swarmspx.alerts.telegram import format_trade_card as tg_format, format_error as tg_error, send_telegram
from swarmspx.alerts.slack import format_trade_card as slack_format, format_error as slack_error, send_slack
from swarmspx.alerts.dispatcher import AlertDispatcher


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_CARD = {
    "direction": "BULL",
    "confidence": 82.5,
    "agreement_pct": 75.0,
    "action": "BUY_CALLS",
    "instrument": "SPX 5200C 0DTE",
    "market_regime": "trending_up",
    "spx_price": 5189.50,
    "vix_level": 14.3,
    "entry_price_est": 12.50,
    "target_price": 18.00,
    "stop_price": 8.00,
    "rationale": "Strong bullish momentum with breadth confirmation.",
    "key_risk": "Fed speakers at 2pm could inject volatility.",
    "contrarian_alert": "Unusually high put/call ratio despite bullish consensus.",
    "herding_warning": "All agents aligned BULL within one round.",
    "timestamp": "2026-03-18T10:30:00",
}

LOW_CONFIDENCE_CARD = {
    "direction": "BEAR",
    "confidence": 55.0,
    "agreement_pct": 50.0,
    "action": "WAIT",
    "instrument": "N/A",
    "market_regime": "choppy",
    "spx_price": 5100.00,
    "vix_level": 18.0,
    "rationale": "Mixed signals.",
    "timestamp": "2026-03-18T11:00:00",
}


# ---------------------------------------------------------------------------
# Telegram formatting
# ---------------------------------------------------------------------------

class TestTelegramFormat:
    def test_format_trade_card_contains_direction(self):
        text = tg_format(SAMPLE_CARD)
        assert "BULL" in text

    def test_format_trade_card_contains_confidence(self):
        text = tg_format(SAMPLE_CARD)
        assert "82" in text  # 82.5 -> "82" after :.0f

    def test_format_trade_card_contains_alerts(self):
        text = tg_format(SAMPLE_CARD)
        assert "Contrarian Alert" in text
        assert "Herding Warning" in text

    def test_format_trade_card_entry_target_stop(self):
        text = tg_format(SAMPLE_CARD)
        assert "12" in text  # entry ~$12.50
        assert "18" in text  # target $18.00
        assert "8" in text   # stop $8.00

    def test_format_error(self):
        text = tg_error("something broke")
        assert "Error" in text
        assert "something broke" in text


# ---------------------------------------------------------------------------
# Slack formatting
# ---------------------------------------------------------------------------

class TestSlackFormat:
    def test_format_trade_card_has_attachments(self):
        payload = slack_format(SAMPLE_CARD)
        assert "attachments" in payload
        assert len(payload["attachments"]) == 1

    def test_format_trade_card_color_bull(self):
        payload = slack_format(SAMPLE_CARD)
        assert payload["attachments"][0]["color"] == "#2ecc71"

    def test_format_trade_card_color_bear(self):
        card = {**SAMPLE_CARD, "direction": "BEAR"}
        payload = slack_format(card)
        assert payload["attachments"][0]["color"] == "#e74c3c"

    def test_format_trade_card_color_neutral(self):
        card = {**SAMPLE_CARD, "direction": "NEUTRAL"}
        payload = slack_format(card)
        assert payload["attachments"][0]["color"] == "#f1c40f"

    def test_format_error_has_attachments(self):
        payload = slack_error("boom")
        assert "attachments" in payload
        assert payload["attachments"][0]["color"] == "#e74c3c"


# ---------------------------------------------------------------------------
# send_telegram / send_slack with missing env vars
# ---------------------------------------------------------------------------

class TestGracefulSkip:
    @pytest.mark.asyncio
    async def test_telegram_skips_without_token(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        result = await send_telegram("hello")
        assert result is False

    @pytest.mark.asyncio
    async def test_slack_skips_without_webhook(self, monkeypatch):
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
        result = await send_slack({"text": "hello"})
        assert result is False


# ---------------------------------------------------------------------------
# send_telegram / send_slack with mocked httpx
# ---------------------------------------------------------------------------

class TestSendWithMock:
    @pytest.mark.asyncio
    async def test_send_telegram_success(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        mock_post = AsyncMock(return_value=mock_response)
        with patch("swarmspx.alerts.telegram.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post = mock_post
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = await send_telegram("test message")
            assert result is True
            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args
            assert "fake-token" in call_kwargs[0][0]
            assert call_kwargs[1]["json"]["chat_id"] == "12345"

    @pytest.mark.asyncio
    async def test_send_slack_success(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        mock_post = AsyncMock(return_value=mock_response)
        with patch("swarmspx.alerts.slack.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post = mock_post
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = await send_slack({"text": "test"})
            assert result is True
            mock_post.assert_called_once()


# ---------------------------------------------------------------------------
# AlertDispatcher integration
# ---------------------------------------------------------------------------

class TestAlertDispatcher:
    @pytest.mark.asyncio
    async def test_dispatches_on_high_confidence(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/x")

        bus = EventBus()
        dispatcher = AlertDispatcher(bus, min_confidence=70.0)

        with patch("swarmspx.alerts.dispatcher.send_telegram", new_callable=AsyncMock) as mock_tg, \
             patch("swarmspx.alerts.dispatcher.send_slack", new_callable=AsyncMock) as mock_sl:
            mock_tg.return_value = True
            mock_sl.return_value = True

            dispatcher.start()
            await bus.emit(TradeCardGenerated(trade_card=SAMPLE_CARD))
            # Give the dispatcher task time to process
            await asyncio.sleep(0.1)
            dispatcher.stop()

            mock_tg.assert_called_once()
            mock_sl.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_low_confidence(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/x")

        bus = EventBus()
        dispatcher = AlertDispatcher(bus, min_confidence=70.0)

        with patch("swarmspx.alerts.dispatcher.send_telegram", new_callable=AsyncMock) as mock_tg, \
             patch("swarmspx.alerts.dispatcher.send_slack", new_callable=AsyncMock) as mock_sl:

            dispatcher.start()
            await bus.emit(TradeCardGenerated(trade_card=LOW_CONFIDENCE_CARD))
            await asyncio.sleep(0.1)
            dispatcher.stop()

            mock_tg.assert_not_called()
            mock_sl.assert_not_called()

    @pytest.mark.asyncio
    async def test_dispatches_engine_error(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/x")

        bus = EventBus()
        dispatcher = AlertDispatcher(bus, min_confidence=70.0)

        with patch("swarmspx.alerts.dispatcher.send_telegram", new_callable=AsyncMock) as mock_tg, \
             patch("swarmspx.alerts.dispatcher.send_slack", new_callable=AsyncMock) as mock_sl:
            mock_tg.return_value = True
            mock_sl.return_value = True

            dispatcher.start()
            await bus.emit(EngineError(message="API rate limit exceeded"))
            await asyncio.sleep(0.1)
            dispatcher.stop()

            mock_tg.assert_called_once()
            mock_sl.assert_called_once()

    @pytest.mark.asyncio
    async def test_custom_threshold(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/x")

        bus = EventBus()
        # Lower threshold so the 55% card should trigger
        dispatcher = AlertDispatcher(bus, min_confidence=50.0)

        with patch("swarmspx.alerts.dispatcher.send_telegram", new_callable=AsyncMock) as mock_tg, \
             patch("swarmspx.alerts.dispatcher.send_slack", new_callable=AsyncMock) as mock_sl:
            mock_tg.return_value = True
            mock_sl.return_value = True

            dispatcher.start()
            await bus.emit(TradeCardGenerated(trade_card=LOW_CONFIDENCE_CARD))
            await asyncio.sleep(0.1)
            dispatcher.stop()

            mock_tg.assert_called_once()
            mock_sl.assert_called_once()
