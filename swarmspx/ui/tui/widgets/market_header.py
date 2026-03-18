"""Market header bar widget - SPX price, VIX, regime badge, cycle timer."""

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class MarketHeader(Widget):
    """Top bar displaying live market data and cycle status."""

    spx_price: reactive[float] = reactive(0.0)
    spx_change_pct: reactive[float] = reactive(0.0)
    vix_level: reactive[float] = reactive(0.0)
    regime: reactive[str] = reactive("--")
    cycle_status: reactive[str] = reactive("IDLE")
    cycle_id: reactive[int] = reactive(0)
    elapsed: reactive[float] = reactive(0.0)

    def compose(self) -> ComposeResult:
        with Horizontal(id="market-header"):
            yield Static("SPX -----.--", id="spx-price")
            yield Static("", id="spx-change")
            yield Static("VIX --.--", id="vix-display")
            yield Static("[--]", id="regime-badge")
            yield Static("", id="cycle-timer")

    def update_market(self, market_context: dict) -> None:
        self.spx_price = market_context.get("spx_price", 0.0)
        self.spx_change_pct = market_context.get("spx_change_pct", 0.0)
        self.vix_level = market_context.get("vix_level", 0.0)
        self.regime = market_context.get("market_regime", "--")

    def watch_spx_price(self, value: float) -> None:
        widget = self.query_one("#spx-price", Static)
        widget.update(f"SPX {value:,.2f}")

    def watch_spx_change_pct(self, value: float) -> None:
        widget = self.query_one("#spx-change", Static)
        if value > 0:
            widget.update(f"[bold green]+{value:.2f}%[/]")
        elif value < 0:
            widget.update(f"[bold red]{value:.2f}%[/]")
        else:
            widget.update(f"[dim]{value:.2f}%[/]")

    def watch_vix_level(self, value: float) -> None:
        widget = self.query_one("#vix-display", Static)
        if value >= 30:
            color = "bold red"
        elif value >= 20:
            color = "bold yellow"
        else:
            color = "green"
        widget.update(f"[{color}]VIX {value:.1f}[/]")

    def watch_regime(self, value: str) -> None:
        widget = self.query_one("#regime-badge", Static)
        color_map = {
            "TRENDING_UP": "bold green",
            "TRENDING_DOWN": "bold red",
            "VOLATILE": "bold yellow",
            "RANGE_BOUND": "cyan",
            "CALM_BULL": "green",
        }
        color = color_map.get(value, "dim white")
        label = value.replace("_", " ").title() if value != "--" else "--"
        widget.update(f"[{color}][{label}][/]")

    def watch_cycle_status(self, value: str) -> None:
        self._refresh_timer()

    def watch_cycle_id(self, value: int) -> None:
        self._refresh_timer()

    def watch_elapsed(self, value: float) -> None:
        self._refresh_timer()

    def _refresh_timer(self) -> None:
        widget = self.query_one("#cycle-timer", Static)
        if self.cycle_status == "RUNNING":
            mins = int(self.elapsed) // 60
            secs = int(self.elapsed) % 60
            widget.update(
                f"[bold #ffd740]CYCLE #{self.cycle_id}[/] "
                f"[dim]{mins:02d}:{secs:02d}[/]"
            )
        elif self.cycle_status == "DONE":
            widget.update(
                f"[green]CYCLE #{self.cycle_id} COMPLETE[/] "
                f"[dim]{self.elapsed:.1f}s[/]"
            )
        else:
            widget.update("[dim]IDLE - press [bold]SPACE[/bold] to start[/]")

    def set_cycle_running(self, cycle_id: int) -> None:
        self.cycle_id = cycle_id
        self.elapsed = 0.0
        self.cycle_status = "RUNNING"

    def set_cycle_done(self, duration: float) -> None:
        self.elapsed = duration
        self.cycle_status = "DONE"

    def tick_elapsed(self, dt: float) -> None:
        if self.cycle_status == "RUNNING":
            self.elapsed += dt
