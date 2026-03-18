import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from swarmspx.report.generator import ReportGenerator

@pytest.mark.asyncio
async def test_report_generates_trade_card():
    with patch("openai.AsyncOpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"action":"BUY","instrument":"SPX 5820C 0DTE","entry_price_est":3.20,"target_price":5.50,"stop_price":1.60,"max_risk_per_contract":320,"rationale":"Strong bullish momentum","key_risk":"VIX spike","time_window":"next 1-2 hours"}'))]
        ))
        gen = ReportGenerator()
        consensus = {
            "direction": "BULL", "confidence": 75.0, "agreement_pct": 71.0,
            "strongest_bull": "VWAP reclaim + positive GEX",
            "strongest_bear": "VIX inverting",
            "contrarian_alert": False, "herding_detected": False,
            "trade_setup": {"direction": "BULL", "action": "BUY"},
            "vote_counts": {"BULL": 17, "BEAR": 5, "NEUTRAL": 2}
        }
        market = {"spx_price": 5800.0, "vix_level": 14.5, "market_regime": "low_vol_grind"}
        card = await gen.generate(consensus, market)
        assert "direction" in card
        assert card["direction"] == "BULL"
