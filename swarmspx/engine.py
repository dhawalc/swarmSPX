import asyncio
import yaml
from swarmspx.ingest.market_data import MarketDataFetcher
from swarmspx.agents.forge import AgentForge
from swarmspx.simulation.pit import TradingPit
from swarmspx.report.generator import ReportGenerator
from swarmspx.memory import AOMemory
from swarmspx.db import Database
from swarmspx.ui.dashboard import render_trade_card, render_agent_grid, render_simulation_progress, console

class SwarmSPXEngine:
    """Main orchestrator for the full simulation pipeline."""

    def __init__(self, settings_path: str = "config/settings.yaml"):
        with open(settings_path) as f:
            self.settings = yaml.safe_load(f)

        self.fetcher = MarketDataFetcher()
        self.forge = AgentForge()
        self.agents = self.forge.create_all()
        self.memory = AOMemory(self.settings["aoms"]["base_url"])
        self.pit = TradingPit(
            agents=self.agents,
            memory=self.memory,
            num_rounds=self.settings["simulation"]["num_rounds"]
        )
        self.reporter = ReportGenerator(
            ollama_base_url=self.settings["ollama"]["base_url"],
            model=self.settings["ollama"]["synthesis_model"]
        )
        self.db = Database(self.settings["database"]["path"])
        self.db.init_schema()

    async def run_cycle(self) -> dict:
        """Run one full simulation cycle."""
        console.rule("[bold blue]SwarmSPX -- New Simulation Cycle[/bold blue]")

        # 1. Fetch market data
        console.print("[dim]Fetching market data...[/dim]")
        market_context = self.fetcher.get_snapshot()
        if not market_context.get("spx_price"):
            console.print("[yellow]Market data unavailable. Retrying next cycle.[/yellow]")
            return {}

        console.print(f"SPX: ${market_context['spx_price']:.2f}  VIX: {market_context['vix_level']:.1f}  Regime: {market_context['market_regime']}")

        # 2. Store snapshot
        self.db.store_snapshot(market_context)

        # 3. Run simulation
        console.print(f"[dim]Running {self.settings['simulation']['num_rounds']}-round simulation with {len(self.agents)} agents...[/dim]")
        consensus = await self.pit.run(market_context)

        # 4. Get AOMS memories for report context
        memories = self.memory.recall(
            f"SPX {market_context['market_regime']} {consensus['direction']} trading",
            limit=5
        )

        # 5. Generate trade card
        console.print("[dim]Synthesizing trade card (Qwen 32B)...[/dim]")
        trade_card = await self.reporter.generate(consensus, market_context, memories)

        # 6. Display
        render_trade_card(trade_card, consensus)
        last_votes = self.pit.agents[0].last_vote and [a.last_vote for a in self.pit.agents if a.last_vote]
        if last_votes:
            render_agent_grid(last_votes)

        # 7. Store to AOMS
        self.memory.store_result(
            direction=consensus["direction"],
            confidence=consensus["confidence"],
            trade_setup=trade_card,
            regime=market_context["market_regime"],
            agent_votes=consensus.get("vote_counts", {})
        )

        # 8. Store to DuckDB
        self.db.store_simulation_result({
            "direction": consensus["direction"],
            "confidence": consensus["confidence"],
            "agreement_pct": consensus["agreement_pct"],
            "trade_setup": trade_card,
            "agent_votes": consensus.get("vote_counts", {}),
        })

        return trade_card
