from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.columns import Columns
from rich.text import Text
from rich import box
from datetime import datetime
from swarmspx.agents.base import AgentVote
from swarmspx.events import (
    EventBus, Event, CycleStarted, MarketDataFetched,
    RoundStarted, AgentVoted, RoundCompleted,
    ConsensusReached, TradeCardGenerated, CycleCompleted, EngineError,
)

console = Console()


class RichConsoleSubscriber:
    """Subscribes to EventBus and renders via Rich console (backward compat)."""

    def __init__(self, bus: EventBus):
        self.bus = bus
        self.bus.on_event(self._handle_event)
        self._last_votes: list[AgentVote] = []

    def _handle_event(self, event: Event):
        if isinstance(event, CycleStarted):
            console.rule("[bold blue]SwarmSPX -- New Simulation Cycle[/bold blue]")
        elif isinstance(event, MarketDataFetched):
            mc = event.market_context
            console.print(f"SPX: ${mc['spx_price']:.2f}  VIX: {mc['vix_level']:.1f}  Regime: {mc['market_regime']}")
        elif isinstance(event, RoundStarted):
            console.print(f"[dim]Round {event.round_num}/{event.total_rounds}...[/dim]")
        elif isinstance(event, RoundCompleted):
            vc = event.vote_counts
            console.print(f"  BULL: {vc.get('BULL',0)}  BEAR: {vc.get('BEAR',0)}  NEUTRAL: {vc.get('NEUTRAL',0)}")
        elif isinstance(event, ConsensusReached):
            c = event.consensus
            color = "green" if c["direction"] == "BULL" else "red" if c["direction"] == "BEAR" else "yellow"
            console.print(f"[bold {color}]Consensus: {c['direction']} @ {c['confidence']:.0f}% confidence ({c['agreement_pct']:.0f}% agreement)[/bold {color}]")
        elif isinstance(event, TradeCardGenerated):
            render_trade_card(event.trade_card, {})
        elif isinstance(event, CycleCompleted):
            console.print(f"[dim]Cycle completed in {event.duration_sec:.1f}s[/dim]")
        elif isinstance(event, EngineError):
            console.print(f"[bold red]ERROR: {event.message}[/bold red]")


def render_trade_card(trade_card: dict, consensus: dict):
    """Render the main trade signal card."""
    direction = trade_card.get("direction", "NEUTRAL")
    confidence = trade_card.get("confidence", 0)
    action = trade_card.get("action", "WAIT")

    color = "green" if direction == "BULL" else "red" if direction == "BEAR" else "yellow"
    action_color = "green" if action == "BUY" else "red" if action == "SELL" else "yellow"

    lines = []
    lines.append(f"[bold {color}]Direction: {direction}[/bold {color}]  [bold]Confidence: {confidence:.0f}%[/bold]  Agreement: {trade_card.get('agreement_pct', 0):.0f}%")
    lines.append(f"Regime: {trade_card.get('market_regime', 'unknown')}  |  SPX: ${trade_card.get('spx_price', 0):.2f}  |  VIX: {trade_card.get('vix_level', 0):.1f}")
    lines.append("")
    lines.append(f"[bold {action_color}]TRADE: {action} {trade_card.get('instrument', 'N/A')}[/bold {action_color}]")
    if trade_card.get("entry_price_est"):
        lines.append(f"Entry: ~${trade_card['entry_price_est']:.2f}  |  Target: ${trade_card.get('target_price', 0):.2f}  |  Stop: ${trade_card.get('stop_price', 0):.2f}")
    lines.append("")
    lines.append(f"[italic]{trade_card.get('rationale', '')}[/italic]")
    if trade_card.get("key_risk"):
        lines.append(f"\n[yellow]Risk: {trade_card['key_risk']}[/yellow]")
    if trade_card.get("contrarian_alert"):
        lines.append("[bold red]CONTRARIAN ALERT: High-conviction minority dissenting[/bold red]")
    if trade_card.get("herding_warning"):
        lines.append("[bold yellow]HERDING WARNING: Agents may be following each other[/bold yellow]")

    timestamp = trade_card.get("timestamp", datetime.now().isoformat())[:19]
    panel = Panel(
        "\n".join(lines),
        title=f"[bold]SwarmSPX Signal -- {timestamp}[/bold]",
        border_style=color,
        box=box.DOUBLE
    )
    console.print(panel)


def render_agent_grid(votes: list[AgentVote]):
    """Render a compact grid of all 24 agent votes."""
    table = Table(title="Agent Votes", box=box.SIMPLE, show_header=True)
    table.add_column("Agent", style="bold", width=18)
    table.add_column("Direction", width=10)
    table.add_column("Conv%", width=6)
    table.add_column("Trade Idea", width=25)

    for vote in votes:
        color = "green" if vote.direction == "BULL" else "red" if vote.direction == "BEAR" else "yellow"
        flip = " ~" if vote.changed_from else ""
        table.add_row(
            vote.agent_id.replace("_", " ").title() + flip,
            f"[{color}]{vote.direction}[/{color}]",
            str(vote.conviction),
            vote.trade_idea[:25] if vote.trade_idea else "WAIT"
        )
    console.print(table)


def render_simulation_progress(round_num: int, total_rounds: int, votes_so_far: int):
    console.print(f"[dim]Round {round_num}/{total_rounds} -- {votes_so_far} agents voted...[/dim]")


def render_error(msg: str):
    console.print(f"[bold red]ERROR: {msg}[/bold red]")
