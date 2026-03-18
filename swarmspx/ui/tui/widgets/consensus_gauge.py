"""Consensus gauge widget - confidence bar and vote breakdown."""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Static


def _confidence_color(pct: float) -> str:
    if pct >= 75:
        return "#00e676"
    elif pct >= 50:
        return "#ffd740"
    else:
        return "#ff5252"


def _build_confidence_bar(pct: float, width: int = 28) -> str:
    filled = max(0, min(width, round(pct / 100 * width)))
    empty = width - filled
    color = _confidence_color(pct)
    return f"[{color}]{'█' * filled}[/][#16162a]{'░' * empty}[/]"


class ConsensusGauge(Widget):
    """Visual gauge showing consensus confidence and vote breakdown."""

    DEFAULT_CSS = """
    ConsensusGauge {
        height: auto;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._consensus: dict | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="consensus-panel"):
            yield Static(
                "[dim]-- No consensus yet --[/]",
                id="confidence-label",
            )
            yield Static("", id="confidence-bar")
            yield Static("", id="agreement-label")
            yield Static("", id="vote-breakdown")
            yield Static("", id="consensus-alerts")

    def set_consensus(self, consensus: dict) -> None:
        self._consensus = consensus
        self._render()

    def reset(self) -> None:
        self._consensus = None
        try:
            self.query_one("#confidence-label", Static).update(
                "[dim]-- No consensus yet --[/]"
            )
            self.query_one("#confidence-bar", Static).update("")
            self.query_one("#agreement-label", Static).update("")
            self.query_one("#vote-breakdown", Static).update("")
            self.query_one("#consensus-alerts", Static).update("")
        except Exception:
            pass

    def _render(self) -> None:
        if not self._consensus:
            return

        c = self._consensus
        direction = c.get("direction", "NEUTRAL")
        confidence = c.get("confidence", 0)
        agreement = c.get("agreement_pct", 0)
        vote_counts = c.get("vote_counts", {})

        dir_color = (
            "green" if direction == "BULL"
            else "red" if direction == "BEAR"
            else "yellow"
        )
        conf_color = _confidence_color(confidence)

        # Confidence label
        try:
            self.query_one("#confidence-label", Static).update(
                f"[bold {dir_color}]{direction}[/]  "
                f"[bold {conf_color}]{confidence:.0f}%[/] confidence"
            )
        except Exception:
            pass

        # Bar
        try:
            self.query_one("#confidence-bar", Static).update(
                _build_confidence_bar(confidence)
            )
        except Exception:
            pass

        # Agreement
        try:
            agr_color = "green" if agreement >= 70 else "yellow" if agreement >= 50 else "red"
            self.query_one("#agreement-label", Static).update(
                f"[{agr_color}]Agreement: {agreement:.0f}%[/]"
            )
        except Exception:
            pass

        # Vote breakdown
        bull = vote_counts.get("BULL", 0)
        bear = vote_counts.get("BEAR", 0)
        neutral = vote_counts.get("NEUTRAL", 0)
        total = bull + bear + neutral or 1

        breakdown = (
            f"[green]\u25b2 BULL  {bull:2d}[/] ({bull/total*100:.0f}%)\n"
            f"[red]\u25bc BEAR  {bear:2d}[/] ({bear/total*100:.0f}%)\n"
            f"[#555570]\u25c6 NEUT  {neutral:2d}[/] ({neutral/total*100:.0f}%)"
        )
        try:
            self.query_one("#vote-breakdown", Static).update(breakdown)
        except Exception:
            pass

        # Alerts
        alerts = []
        if confidence < 40:
            alerts.append("[yellow]\u26a0 Low confidence - consider smaller size[/]")
        if agreement < 50:
            alerts.append("[yellow]\u26a0 Weak agreement - swarm is divided[/]")
        flip_count = c.get("flip_count", 0)
        if flip_count >= 6:
            alerts.append(f"[red]\u26a0 {flip_count} agents flipped - unstable consensus[/]")

        try:
            self.query_one("#consensus-alerts", Static).update(
                "\n".join(alerts) if alerts else ""
            )
        except Exception:
            pass
