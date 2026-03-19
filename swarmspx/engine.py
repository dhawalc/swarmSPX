import asyncio
import logging
import time
import yaml
from typing import Optional
from swarmspx.ingest.market_data import MarketDataFetcher
from swarmspx.agents.forge import AgentForge
from swarmspx.simulation.pit import TradingPit
from swarmspx.report.generator import ReportGenerator
from swarmspx.providers import resolve_synthesis_model
from swarmspx.memory import AOMemory
from swarmspx.db import Database
from swarmspx.scoring import AgentScorer
from swarmspx.events import (
    EventBus, NoOpBus,
    CycleStarted, MarketDataFetched, ConsensusReached,
    TradeCardGenerated, CycleCompleted, EngineError,
    OutcomeResolved,
)
from swarmspx.tracking.outcome_tracker import OutcomeTracker
from swarmspx.strategy.selector import select_strategy

logger = logging.getLogger(__name__)

class SwarmSPXEngine:
    """Main orchestrator for the full simulation pipeline."""

    def __init__(self, settings_path: str = "config/settings.yaml", bus: Optional[EventBus] = None):
        with open(settings_path) as f:
            self.settings = yaml.safe_load(f)

        self.bus = bus or NoOpBus()
        self.cycle_count = 0

        self.fetcher = MarketDataFetcher()
        self.forge = AgentForge()
        self.agents = self.forge.create_all()
        self.memory = AOMemory(self.settings["aoms"]["base_url"])
        self.pit = TradingPit(
            agents=self.agents,
            memory=self.memory,
            num_rounds=self.settings["simulation"]["num_rounds"],
            bus=self.bus,
        )
        synth_cfg = resolve_synthesis_model(self.settings)
        self.reporter = ReportGenerator(
            ollama_base_url=synth_cfg["base_url"],
            model=synth_cfg["model"],
            api_key=synth_cfg["api_key"],
            use_claude_cli=synth_cfg["use_claude_cli"],
            claude_model=synth_cfg["claude_model"],
        )
        self.db = Database(self.settings["database"]["path"])
        self.db.init_schema()
        self.scorer = AgentScorer(self.db)
        self.tracker = OutcomeTracker(self.db, self.fetcher, self.memory, self.bus, self.scorer)

    async def run_cycle(self) -> dict:
        """Run one full simulation cycle."""
        self.cycle_count += 1
        start = time.time()
        await self.bus.emit(CycleStarted(cycle_id=self.cycle_count))

        # 1. Fetch market data
        market_context = self.fetcher.get_snapshot()
        if not market_context.get("spx_price"):
            await self.bus.emit(EngineError(message="Market data unavailable"))
            return {}

        # 1b. Enrich with live options chain (if Tradier configured)
        await self.fetcher.enrich_with_options(market_context)

        await self.bus.emit(MarketDataFetched(market_context=market_context))

        # 2. Store snapshot
        self.db.store_snapshot(market_context)

        # 3. Get agent weights for current regime and run simulation
        regime = market_context.get("market_regime", "unknown")
        agent_weights = self.scorer.get_weights(regime)
        consensus = await self.pit.run(market_context, agent_weights=agent_weights)
        await self.bus.emit(ConsensusReached(consensus=consensus))

        # 4. Select strategy based on consensus + regime + options
        strategy = select_strategy(
            consensus, market_context, self.fetcher._options_snapshot,
        )
        market_context["selected_strategy"] = strategy

        # 5. Get AOMS memories for report context
        memories = self.memory.recall(
            f"SPX {market_context['market_regime']} {consensus['direction']} trading",
            limit=5
        )

        # 6. Generate trade card
        trade_card = await self.reporter.generate(consensus, market_context, memories)
        await self.bus.emit(TradeCardGenerated(trade_card=trade_card))

        # 7. Store to AOMS
        memory_id = self.memory.store_result(
            direction=consensus["direction"],
            confidence=consensus["confidence"],
            trade_setup=trade_card,
            regime=market_context["market_regime"],
            agent_votes=consensus.get("vote_counts", {})
        )

        # 8. Store to DuckDB
        signal_id = self.db.store_simulation_result({
            "direction": consensus["direction"],
            "confidence": consensus["confidence"],
            "agreement_pct": consensus["agreement_pct"],
            "spx_entry_price": market_context.get("spx_price", 0.0),
            "memory_id": memory_id,
            "trade_setup": trade_card,
            "agent_votes": consensus.get("vote_counts", {}),
        })

        # 8b. Store individual agent votes for Darwinian scoring
        if signal_id and consensus.get("individual_votes"):
            self.db.store_agent_votes(signal_id, consensus["individual_votes"], regime)
            logger.info("Stored %d individual agent votes for signal #%d",
                       len(consensus["individual_votes"]), signal_id)

        # 9. Check and resolve pending signals
        await self.tracker.check_pending_signals()

        duration = time.time() - start
        await self.bus.emit(CycleCompleted(cycle_id=self.cycle_count, duration_sec=duration))

        return trade_card
