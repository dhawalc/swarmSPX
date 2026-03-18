"""SwarmSPX Textual TUI - Professional trading terminal for the 24-agent swarm."""

import asyncio
import time
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, Footer
from textual.worker import Worker, get_current_worker

from swarmspx.events import (
    EventBus,
    Event,
    CycleStarted,
    MarketDataFetched,
    RoundStarted,
    AgentVoted,
    RoundCompleted,
    ConsensusReached,
    TradeCardGenerated,
    CycleCompleted,
    EngineError,
)

from swarmspx.ui.tui.widgets.market_header import MarketHeader
from swarmspx.ui.tui.widgets.agent_heatmap import AgentHeatmap
from swarmspx.ui.tui.widgets.round_progress import RoundProgress
from swarmspx.ui.tui.widgets.trade_card import TradeCard
from swarmspx.ui.tui.widgets.consensus_gauge import ConsensusGauge


CSS_PATH = Path(__file__).parent / "swarm.tcss"


class SwarmSPXApp(App):
    """Main TUI application for SwarmSPX trading swarm."""

    TITLE = "SwarmSPX"
    SUB_TITLE = "24-Agent Trading Swarm"
    CSS_PATH = CSS_PATH

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("r", "force_cycle", "New Cycle", show=True),
        Binding("space", "toggle_pause", "Pause/Resume", show=True),
    ]

    def __init__(
        self,
        bus: EventBus,
        engine=None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.bus = bus
        self.engine = engine
        self._paused = False
        self._cycle_start_time: float = 0
        self._timer_handle = None
        self._event_worker: Worker | None = None

    def compose(self) -> ComposeResult:
        yield MarketHeader()
        with Horizontal(id="main-container"):
            yield AgentHeatmap()
            yield TradeCard()
            with Vertical(id="right-column"):
                yield RoundProgress()
                yield ConsensusGauge()
        with Horizontal(id="status-bar"):
            yield Static(
                "[dim]SwarmSPX v1.0  |  24 agents  |  4 tribes[/]",
                id="status-left",
            )
            yield Static(
                "[dim]q:Quit  r:New Cycle  SPACE:Pause[/]",
                id="status-right",
            )
        yield Footer()

    def on_mount(self) -> None:
        # Start the event listener worker
        self._event_worker = self.run_worker(
            self._event_loop, exclusive=True, thread=False
        )
        # Timer for elapsed display
        self._timer_handle = self.set_interval(1.0, self._tick_timer)

    async def _event_loop(self) -> None:
        """Background worker that reads events from the EventBus queue."""
        queue = self.bus.subscribe()
        worker = get_current_worker()
        while not worker.is_cancelled:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=0.25)
            except (asyncio.TimeoutError, TimeoutError):
                continue
            except asyncio.CancelledError:
                break

            if self._paused:
                continue

            # Dispatch event to handler on the main thread
            self.call_from_thread(self._dispatch_event, event) if False else self._dispatch_event(event)

    def _dispatch_event(self, event: Event) -> None:
        """Route an event to the appropriate widget update."""
        if isinstance(event, CycleStarted):
            self._on_cycle_started(event)
        elif isinstance(event, MarketDataFetched):
            self._on_market_data(event)
        elif isinstance(event, RoundStarted):
            self._on_round_started(event)
        elif isinstance(event, AgentVoted):
            self._on_agent_voted(event)
        elif isinstance(event, RoundCompleted):
            self._on_round_completed(event)
        elif isinstance(event, ConsensusReached):
            self._on_consensus(event)
        elif isinstance(event, TradeCardGenerated):
            self._on_trade_card(event)
        elif isinstance(event, CycleCompleted):
            self._on_cycle_completed(event)
        elif isinstance(event, EngineError):
            self._on_error(event)

    # ── Event Handlers ──

    def _on_cycle_started(self, event: CycleStarted) -> None:
        self._cycle_start_time = time.time()
        header = self.query_one(MarketHeader)
        header.set_cycle_running(event.cycle_id)

        # Reset widgets for new cycle
        self.query_one(AgentHeatmap).reset_all()
        self.query_one(RoundProgress).reset()
        self.query_one(TradeCard).clear()
        self.query_one(ConsensusGauge).reset()

        self._set_status(f"Cycle #{event.cycle_id} started...")

    def _on_market_data(self, event: MarketDataFetched) -> None:
        header = self.query_one(MarketHeader)
        header.update_market(event.market_context)
        self._set_status("Market data received")

    def _on_round_started(self, event: RoundStarted) -> None:
        rp = self.query_one(RoundProgress)
        rp.set_current_round(event.round_num)
        self._set_status(
            f"Round {event.round_num}/{event.total_rounds} - agents voting..."
        )

    def _on_agent_voted(self, event: AgentVoted) -> None:
        heatmap = self.query_one(AgentHeatmap)
        heatmap.update_agent_vote(
            agent_id=event.agent_id,
            direction=event.direction,
            conviction=event.conviction,
            changed_from=event.changed_from,
        )

    def _on_round_completed(self, event: RoundCompleted) -> None:
        rp = self.query_one(RoundProgress)
        rp.set_round_result(event.round_num, event.vote_counts)
        self._set_status(
            f"Round {event.round_num} complete - "
            f"B:{event.vote_counts.get('BULL',0)} "
            f"R:{event.vote_counts.get('BEAR',0)} "
            f"N:{event.vote_counts.get('NEUTRAL',0)}"
        )

    def _on_consensus(self, event: ConsensusReached) -> None:
        gauge = self.query_one(ConsensusGauge)
        gauge.set_consensus(event.consensus)
        self._set_status("Consensus reached - generating trade card...")

    def _on_trade_card(self, event: TradeCardGenerated) -> None:
        tc = self.query_one(TradeCard)
        tc.set_trade(event.trade_card)
        self._set_status("Trade card generated")

    def _on_cycle_completed(self, event: CycleCompleted) -> None:
        header = self.query_one(MarketHeader)
        header.set_cycle_done(event.duration_sec)
        self._set_status(
            f"Cycle #{event.cycle_id} complete in {event.duration_sec:.1f}s"
        )

    def _on_error(self, event: EngineError) -> None:
        self._set_status(f"[bold red]ERROR: {event.message}[/]")

    # ── Timer ──

    def _tick_timer(self) -> None:
        header = self.query_one(MarketHeader)
        header.tick_elapsed(1.0)

    # ── Actions ──

    def action_force_cycle(self) -> None:
        """Trigger a new simulation cycle."""
        if self.engine is not None:
            self._set_status("[#ffd740]Forcing new cycle...[/]")
            self.run_worker(self._run_engine_cycle, exclusive=False, thread=False)
        else:
            self._set_status("[yellow]No engine attached - view only mode[/]")

    async def _run_engine_cycle(self) -> None:
        try:
            await self.engine.run_cycle()
        except Exception as e:
            self.call_from_thread(
                self._set_status,
                f"[bold red]Engine error: {e}[/]",
            ) if False else self._set_status(f"[bold red]Engine error: {e}[/]")

    def action_toggle_pause(self) -> None:
        self._paused = not self._paused
        if self._paused:
            self._set_status("[yellow]PAUSED[/] - press SPACE to resume")
        else:
            self._set_status("[green]RESUMED[/]")

    # ── Helpers ──

    def _set_status(self, text: str) -> None:
        try:
            self.query_one("#status-left", Static).update(
                f"[dim]{text}[/]"
            )
        except Exception:
            pass


def run_tui(bus: EventBus, engine=None) -> None:
    """Entry point to launch the TUI."""
    app = SwarmSPXApp(bus=bus, engine=engine)
    app.run()
