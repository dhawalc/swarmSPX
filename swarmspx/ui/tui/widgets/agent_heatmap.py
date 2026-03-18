"""Agent heatmap widget - 4-tribe vote grid with 24 agents."""

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.widget import Widget
from textual.widgets import Static

# Canonical agent definitions per tribe
TRIBES = {
    "technical": {
        "label": "TECHNICAL",
        "agents": [
            "vwap_victor", "gamma_gary", "delta_dawn",
            "momentum_mike", "level_lucy", "tick_tina",
        ],
    },
    "macro": {
        "label": "MACRO",
        "agents": [
            "fed_fred", "flow_fiona", "vix_vinny",
            "gex_gina", "putcall_pete", "breadth_brad",
        ],
    },
    "sentiment": {
        "label": "SENTIMENT",
        "agents": [
            "twitter_tom", "contrarian_carl", "fear_felicia",
            "news_nancy", "retail_ray", "whale_wanda",
        ],
    },
    "strategists": {
        "label": "STRATEGY",
        "agents": [
            "calendar_cal", "spread_sam", "scalp_steve",
            "swing_sarah", "risk_rick", "synthesis_syd",
        ],
    },
}

DIRECTION_ARROWS = {"BULL": "\u25b2", "BEAR": "\u25bc", "NEUTRAL": "\u25c6"}
DIRECTION_COLORS = {"BULL": "green", "BEAR": "red", "NEUTRAL": "#555570"}


def _short_name(agent_id: str) -> str:
    """Convert agent_id to a short display name."""
    parts = agent_id.split("_")
    if len(parts) >= 2:
        return parts[0][:4].upper() + " " + parts[1][0].upper()
    return agent_id[:6].upper()


class AgentCell(Static):
    """Single agent cell in the heatmap."""

    DEFAULT_CSS = """
    AgentCell {
        height: 1;
        width: 1fr;
        padding: 0;
    }
    """

    def __init__(self, agent_id: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.agent_id = agent_id
        self.direction = ""
        self.conviction = 0
        self.flipped = False
        self._short = _short_name(agent_id)

    def set_vote(
        self, direction: str, conviction: int, changed_from: str | None = None
    ) -> None:
        self.direction = direction
        self.conviction = conviction
        self.flipped = changed_from is not None
        self._render_cell()

    def flash_active(self) -> None:
        """Briefly highlight the cell when a vote arrives."""
        self.add_class("active")
        self.set_timer(0.8, self._remove_active)

    def _remove_active(self) -> None:
        self.remove_class("active")

    def _render_cell(self) -> None:
        arrow = DIRECTION_ARROWS.get(self.direction, " ")
        color = DIRECTION_COLORS.get(self.direction, "#555570")
        flip_marker = "\u21c4" if self.flipped else " "
        conv_str = f"{self.conviction:2d}" if self.conviction else "--"
        markup = (
            f"[{color}]{arrow} {self._short} {conv_str}{flip_marker}[/]"
        )
        self.update(markup)

        self.remove_class("bull", "bear", "neutral", "flipped")
        if self.direction:
            self.add_class(self.direction.lower())
        if self.flipped:
            self.add_class("flipped")

    def reset(self) -> None:
        self.direction = ""
        self.conviction = 0
        self.flipped = False
        self.update(f"[#333350]  {self._short} --  [/]")
        self.remove_class("bull", "bear", "neutral", "flipped", "active")


class AgentHeatmap(Widget):
    """4-column tribal vote heatmap for all 24 agents."""

    DEFAULT_CSS = """
    AgentHeatmap {
        height: 1fr;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._cells: dict[str, AgentCell] = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="agent-heatmap-panel"):
            with Horizontal(id="heatmap-grid"):
                for tribe_key, tribe_info in TRIBES.items():
                    with Vertical(classes="tribe-column"):
                        yield Static(
                            tribe_info["label"],
                            classes="tribe-header",
                        )
                        for agent_id in tribe_info["agents"]:
                            cell = AgentCell(agent_id, classes="agent-cell")
                            self._cells[agent_id] = cell
                            yield cell

    def on_mount(self) -> None:
        for cell in self._cells.values():
            cell.reset()

    def update_agent_vote(
        self,
        agent_id: str,
        direction: str,
        conviction: int,
        changed_from: str | None = None,
    ) -> None:
        cell = self._cells.get(agent_id)
        if cell:
            cell.set_vote(direction, conviction, changed_from)
            cell.flash_active()

    def reset_all(self) -> None:
        for cell in self._cells.values():
            cell.reset()
