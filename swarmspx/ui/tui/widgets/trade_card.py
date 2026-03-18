"""Hero trade card widget - prominent signal display."""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Static


BULL_ART = r"""
     /\
    /  \  BULL
   / ▲▲ \
  /______\
"""

BEAR_ART = r"""
   \      /
    \    /  BEAR
     \▼▼/
      \/
"""

NEUTRAL_ART = r"""
   ◇─────◇
   │WAIT │
   ◇─────◇
"""


class TradeCard(Widget):
    """Large hero panel showing the final trade signal."""

    DEFAULT_CSS = """
    TradeCard {
        height: 1fr;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._trade_data: dict | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="trade-card-panel"):
            yield Static(
                "[dim italic]Awaiting consensus...[/]",
                id="trade-direction",
            )
            yield Static("", id="trade-action")
            yield Static("", id="trade-levels")
            yield Static("", id="trade-rationale")
            yield Static("", id="trade-alerts")

    def set_trade(self, trade_card: dict) -> None:
        self._trade_data = trade_card
        self._render()

    def clear(self) -> None:
        self._trade_data = None
        try:
            self.query_one("#trade-direction", Static).update(
                "[dim italic]Awaiting consensus...[/]"
            )
            self.query_one("#trade-action", Static).update("")
            self.query_one("#trade-levels", Static).update("")
            self.query_one("#trade-rationale", Static).update("")
            self.query_one("#trade-alerts", Static).update("")
        except Exception:
            pass

    def _render(self) -> None:
        if not self._trade_data:
            return

        tc = self._trade_data
        direction = tc.get("direction", "NEUTRAL")
        confidence = tc.get("confidence", 0)
        agreement = tc.get("agreement_pct", 0)
        action = tc.get("action", "WAIT")

        # Direction header with ASCII art
        if direction == "BULL":
            dir_color = "bold green"
            art = BULL_ART
        elif direction == "BEAR":
            dir_color = "bold red"
            art = BEAR_ART
        else:
            dir_color = "bold yellow"
            art = NEUTRAL_ART

        dir_text = (
            f"[{dir_color}]{art}\n"
            f"  {direction}  |  {confidence:.0f}% confidence  |  "
            f"{agreement:.0f}% agreement[/]"
        )
        try:
            self.query_one("#trade-direction", Static).update(dir_text)
        except Exception:
            pass

        # Action line
        action_color = "green" if action == "BUY" else "red" if action == "SELL" else "yellow"
        instrument = tc.get("instrument", "N/A")
        action_text = f"[bold {action_color}]\u2588\u2588 {action} {instrument} \u2588\u2588[/]"
        try:
            self.query_one("#trade-action", Static).update(action_text)
        except Exception:
            pass

        # Entry / Target / Stop
        lines = []
        entry = tc.get("entry_price_est")
        target = tc.get("target_price")
        stop = tc.get("stop_price")
        if entry:
            lines.append(
                f"[bold white]Entry:[/]  ${entry:,.2f}    "
                f"[bold green]Target:[/] ${target:,.2f}    "
                f"[bold red]Stop:[/]   ${stop:,.2f}"
            )
        regime = tc.get("market_regime", "")
        spx = tc.get("spx_price", 0)
        vix = tc.get("vix_level", 0)
        if regime:
            lines.append(
                f"[dim]Regime: {regime}  |  SPX: ${spx:,.2f}  |  VIX: {vix:.1f}[/]"
            )
        try:
            self.query_one("#trade-levels", Static).update("\n".join(lines))
        except Exception:
            pass

        # Rationale
        rationale = tc.get("rationale", "")
        if rationale:
            # Wrap long rationale
            wrapped = rationale[:300]
            if len(rationale) > 300:
                wrapped += "..."
            try:
                self.query_one("#trade-rationale", Static).update(
                    f"[italic #8080a0]{wrapped}[/]"
                )
            except Exception:
                pass

        # Alerts
        alerts = []
        if tc.get("key_risk"):
            alerts.append(f"[yellow]\u26a0 RISK: {tc['key_risk']}[/]")
        if tc.get("contrarian_alert"):
            alerts.append(
                "[bold red]\u26a0 CONTRARIAN ALERT: High-conviction minority dissenting[/]"
            )
        if tc.get("herding_warning"):
            alerts.append(
                "[bold yellow]\u26a0 HERDING WARNING: Agents may be echo-chambering[/]"
            )
        try:
            self.query_one("#trade-alerts", Static).update("\n".join(alerts))
        except Exception:
            pass
