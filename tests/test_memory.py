"""Tests for swarmspx.memory — async AOMS client."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from swarmspx.memory import AOMemory


def test_recall_returns_memories():
    async def _run():
        mock_resp = MagicMock(
            status_code=200,
            json=lambda: {"results": [{"content": "test memory", "score": 0.9}]},
        )
        with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_resp)):
            mem = AOMemory(base_url="http://localhost:9100")
            results = await mem.recall("SPX trading setup")
            await mem.aclose()
            return results

    results = asyncio.run(_run())
    assert len(results) > 0
    assert "content" in results[0]


def test_store_simulation_result():
    async def _run():
        mock_resp = MagicMock(status_code=200, json=lambda: {"id": "abc123"})
        with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_resp)):
            mem = AOMemory(base_url="http://localhost:9100")
            result = await mem.store_result(
                direction="BULL",
                confidence=75.0,
                trade_setup={"strike": 5820, "type": "call"},
                regime="low_vol_grind",
            )
            await mem.aclose()
            return result

    result = asyncio.run(_run())
    assert result == "abc123"


def test_recall_handles_failure_gracefully():
    """When AOMS is down, recall returns [] not an exception."""
    async def _run():
        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=Exception("connection refused"))):
            mem = AOMemory(base_url="http://localhost:9100")
            result = await mem.recall("query")
            await mem.aclose()
            return result

    assert asyncio.run(_run()) == []


def test_store_outcome_swallows_failures():
    """store_outcome is best-effort; failures must not raise."""
    async def _run():
        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=Exception("AOMS down"))):
            mem = AOMemory(base_url="http://localhost:9100")
            await mem.store_outcome("memid", "win", 50.0)  # must not raise
            await mem.aclose()

    asyncio.run(_run())  # passes if no exception
