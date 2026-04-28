"""Integration tests for Tier 1 wiring inside SwarmSPXEngine.run_cycle.

Verifies:
    - Kill switch tripped → cycle short-circuits, no DB write.
    - GEX: when chain exists, market_context gains gex_block / gex_regime.
    - Risk gate rejected → signal persisted with outcome='gated', no
      TradeCardGenerated emitted.
    - Kelly sizing populated on the trade card.
    - Happy path: TradeCardGenerated emitted, signal outcome='pending'.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import yaml

from swarmspx.clock import now_et
from swarmspx.events import EngineError, EventBus, TradeCardGenerated


# ── Helper to build a stubbed engine without spinning up agents/Ollama ───────

def _make_engine(tmp_path, monkeypatch, settings_overrides=None):
    """Build SwarmSPXEngine with all heavy deps mocked.

    Bypasses LLM agent construction (which needs Ollama) by patching
    AgentForge.create_all to return [].
    """
    from swarmspx.engine import SwarmSPXEngine

    base_settings = {
        "providers": {
            "ollama": {"base_url": "http://localhost:11434/v1", "api_key": "ollama"},
        },
        "models": {
            "fast_local":    {"provider": "ollama", "model": "llama3.1:8b"},
            "premium_local": {"provider": "ollama", "model": "phi4:14b"},
        },
        "tribe_models": {
            "technical": "fast_local", "macro": "fast_local",
            "sentiment": "fast_local", "strategists": "premium_local",
        },
        "synthesis_model": "premium_local",
        "aoms": {"base_url": "http://localhost:9100"},
        "simulation": {"num_rounds": 1, "cycle_interval_sec": 300, "conviction_threshold": 70},
        "database": {"path": ":memory:"},
        "risk": {
            "bankroll_usd": 25_000.0,
            "killswitch_state_path": str(tmp_path / "ks.json"),
            "lock_dir": str(tmp_path),
        },
    }
    if settings_overrides:
        base_settings.update(settings_overrides)
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(yaml.safe_dump(base_settings))

    monkeypatch.setattr(
        "swarmspx.agents.forge.AgentForge.create_all",
        lambda self: [],
    )
    monkeypatch.setattr(
        "swarmspx.report.generator.ReportGenerator.generate",
        AsyncMock(return_value={"direction": "BULL", "rationale": "test"}),
    )
    monkeypatch.setattr(
        "swarmspx.memory.AOMemory.recall",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "swarmspx.memory.AOMemory.store_result",
        AsyncMock(return_value="memid"),
    )
    monkeypatch.setattr(
        "swarmspx.memory.AOMemory.store_outcome",
        AsyncMock(return_value=None),
    )

    bus = EventBus()
    engine = SwarmSPXEngine(settings_path=str(settings_path), bus=bus)
    return engine, bus


def _stub_market_data(engine):
    """Plumb a deterministic market snapshot into the engine's fetcher."""
    snap = {
        "timestamp": now_et().isoformat(),
        "spx_price": 5450.0,
        "spx_change_pct": 0.5,
        "spx_vwap": 5448.0,
        "spx_vwap_distance_pct": 0.04,
        "vix_level": 14.0,
        "vix_change": 0.0,
        "put_call_ratio": 1.0,
        "market_regime": "normal_vol",
        "is_market_hours": True,
        "data_source": "stub",
    }
    engine.fetcher.get_snapshot = MagicMock(return_value=snap)
    engine.fetcher.enrich_with_options = AsyncMock(return_value=snap)
    return snap


def _stub_consensus(engine, direction="BULL"):
    consensus = {
        "direction": direction,
        "confidence": 80.0,
        "agreement_pct": 75.0,
        "vote_counts": {"BULL": 18, "BEAR": 4, "NEUTRAL": 2},
        "rounds": 1,
        "individual_votes": [],
        "weighted_direction": direction,
    }
    engine.pit.run = AsyncMock(return_value=consensus)
    return consensus


# ── Tests ────────────────────────────────────────────────────────────────────

class TestEngineWiring:

    def test_killswitch_short_circuits_cycle(self, tmp_path, monkeypatch):
        engine, bus = _make_engine(tmp_path, monkeypatch)
        engine.killswitch.trip("manual", "test trip")

        events = []
        def _capture(e):
            if isinstance(e, EngineError):
                events.append(("error", e))
            elif isinstance(e, TradeCardGenerated):
                events.append(("card", e))
        bus.on_event(_capture)

        result = asyncio.run(engine.run_cycle())
        assert result == {}
        # No card emitted when kill switch is tripped
        assert not any(t == "card" for t, _ in events)
        # No DB writes during a short-circuited cycle
        assert engine.db.get_signal_stats()["total"] == 0

    def test_happy_path_emits_card_and_persists_pending(self, tmp_path, monkeypatch):
        engine, bus = _make_engine(tmp_path, monkeypatch)
        _stub_market_data(engine)
        _stub_consensus(engine)

        cards = []
        def _capture_card(e):
            if isinstance(e, TradeCardGenerated):
                cards.append(e.trade_card)
        bus.on_event(_capture_card)

        result = asyncio.run(engine.run_cycle())
        assert result is not None
        assert "sizing" in result  # Kelly injected
        assert "risk_decision" in result
        assert result["risk_decision"]["action"] == "PASS"

        assert len(cards) == 1
        signals = engine.db.get_recent_signals(limit=5)
        assert len(signals) == 1
        assert signals[0]["outcome"] == "pending"

    def test_risk_gate_rejection_persists_as_gated(self, tmp_path, monkeypatch):
        engine, bus = _make_engine(tmp_path, monkeypatch)
        _stub_market_data(engine)
        # NEUTRAL consensus → gate rejects with non_directional
        _stub_consensus(engine, direction="NEUTRAL")

        cards = []
        def _capture_card(e):
            if isinstance(e, TradeCardGenerated):
                cards.append(e.trade_card)
        bus.on_event(_capture_card)

        result = asyncio.run(engine.run_cycle())
        # Card returned to caller, but NOT emitted to dispatcher
        assert "risk_decision" in result
        assert result["risk_decision"]["action"] == "REJECT"
        assert "non_directional" in result["risk_decision"]["reasons"]
        assert len(cards) == 0

        signals = engine.db.get_recent_signals(limit=5)
        assert len(signals) == 1
        assert signals[0]["outcome"] == "gated"

    def test_gex_injected_when_chain_present(self, tmp_path, monkeypatch):
        engine, bus = _make_engine(tmp_path, monkeypatch)
        _stub_market_data(engine)
        _stub_consensus(engine)

        from swarmspx.ingest.options import OptionContract, OptionsSnapshot
        contracts = [
            OptionContract(
                strike=5450.0, option_type="call",
                bid=5.0, ask=5.5, mid=5.25, spread=0.5,
                volume=100, open_interest=10_000,
                delta=0.5, gamma=0.05, theta=-0.5, vega=0.5, iv=15.0,
            ),
            OptionContract(
                strike=5400.0, option_type="put",
                bid=4.0, ask=4.5, mid=4.25, spread=0.5,
                volume=100, open_interest=10_000,
                delta=-0.4, gamma=0.04, theta=-0.4, vega=0.4, iv=16.0,
            ),
        ]
        engine.fetcher._options_snapshot = OptionsSnapshot(contracts=contracts)

        captured = {}

        async def _capture_run(market_context, agent_weights=None):
            captured["mc"] = dict(market_context)
            return {
                "direction": "BULL", "confidence": 80.0, "agreement_pct": 75.0,
                "vote_counts": {}, "rounds": 1, "individual_votes": [],
                "weighted_direction": "BULL",
            }
        engine.pit.run = _capture_run

        asyncio.run(engine.run_cycle())
        assert "gex_block" in captured["mc"]
        assert "DEALER POSITIONING" in captured["mc"]["gex_block"]
        assert "gex_regime" in captured["mc"]
