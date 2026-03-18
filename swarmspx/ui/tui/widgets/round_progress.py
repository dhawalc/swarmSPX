"""Round progression widget - shows rounds 1-5 with vote distribution bars."""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Static


def _build_bar(bull: int, bear: int, neutral: int, width: int = 22) -> str:
    """Build a colored stacked bar from vote counts."""
    total = bull + bear + neutral
    if total == 0:
        return f"[#16162a]{'░' * width}[/]"

    bull_w = max(1, round(bull / total * width)) if bull else 0
    bear_w = max(1, round(bear / total * width)) if bear else 0
    neutral_w = width - bull_w - bear_w
    if neutral_w < 0:
        # Adjust if rounding pushed us over
        if bull_w > bear_w:
            bull_w += neutral_w
        else:
            bear_w += neutral_w
        neutral_w = 0

    bar = ""
    if bull_w:
        bar += f"[on #00692f]{'█' * bull_w}[/]"
    if bear_w:
        bar += f"[on #8b0000]{'█' * bear_w}[/]"
    if neutral_w:
        bar += f"[on #2a2a3e]{'░' * neutral_w}[/]"

    counts = f" [green]{bull}[/][dim]/[/][red]{bear}[/][dim]/[/][#555570]{neutral}[/]"
    return bar + counts


class RoundProgress(Widget):
    """Displays round-by-round progression with vote distribution."""

    DEFAULT_CSS = """
    RoundProgress {
        height: 1fr;
    }
    """

    TOTAL_ROUNDS = 5

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._round_data: dict[int, dict] = {}
        self._current_round = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="round-progress-panel"):
            for r in range(1, self.TOTAL_ROUNDS + 1):
                yield Static(
                    self._render_round(r),
                    id=f"round-row-{r}",
                    classes="round-row",
                )

    def on_mount(self) -> None:
        self._refresh_all()

    def set_current_round(self, round_num: int) -> None:
        self._current_round = round_num
        self._refresh_all()

    def set_round_result(self, round_num: int, vote_counts: dict) -> None:
        self._round_data[round_num] = vote_counts
        self._current_round = round_num
        self._refresh_all()

    def reset(self) -> None:
        self._round_data.clear()
        self._current_round = 0
        self._refresh_all()

    def _render_round(self, r: int) -> str:
        is_active = r == self._current_round
        is_done = r in self._round_data

        if is_active and not is_done:
            label = f"[bold #ffd740]R{r} \u25b6 [/]"
        elif is_done:
            label = f"[#7070a0]R{r} \u2713 [/]"
        else:
            label = f"[#333350]R{r}   [/]"

        if is_done:
            vc = self._round_data[r]
            bar = _build_bar(
                vc.get("BULL", 0),
                vc.get("BEAR", 0),
                vc.get("NEUTRAL", 0),
            )
        elif is_active:
            bar = f"[#ffd740]{'.' * 22}[/] [dim]voting...[/]"
        else:
            bar = f"[#16162a]{'░' * 22}[/]"

        return f"{label}{bar}"

    def _refresh_all(self) -> None:
        for r in range(1, self.TOTAL_ROUNDS + 1):
            try:
                widget = self.query_one(f"#round-row-{r}", Static)
                widget.update(self._render_round(r))
            except Exception:
                pass
