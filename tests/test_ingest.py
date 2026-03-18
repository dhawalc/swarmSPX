import pytest
from swarmspx.ingest.market_data import MarketDataFetcher
from swarmspx.db import Database

def test_fetch_spx_returns_price():
    fetcher = MarketDataFetcher()
    data = fetcher.get_snapshot()
    assert "spx_price" in data
    assert "vix_level" in data
    assert isinstance(data["spx_price"], float)
    assert data["spx_price"] > 0

def test_database_stores_snapshot():
    db = Database(":memory:")
    db.init_schema()
    snapshot = {"spx_price": 5800.0, "vix_level": 15.2, "timestamp": "2026-03-17T10:00:00"}
    db.store_snapshot(snapshot)
    result = db.get_latest_snapshot()
    assert result["spx_price"] == 5800.0
