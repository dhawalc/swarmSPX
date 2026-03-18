import pytest
from unittest.mock import patch, MagicMock
from swarmspx.memory import AOMemory

def test_recall_returns_memories():
    with patch("httpx.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"results": [{"content": "test memory", "score": 0.9}]}
        )
        mem = AOMemory(base_url="http://localhost:9100")
        results = mem.recall("SPX trading setup")
        assert len(results) > 0
        assert "content" in results[0]

def test_store_simulation_result():
    with patch("httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"id": "abc123"})
        mem = AOMemory(base_url="http://localhost:9100")
        result = mem.store_result(
            direction="BULL",
            confidence=75.0,
            trade_setup={"strike": 5820, "type": "call"},
            regime="low_vol_grind"
        )
        assert result is not None
