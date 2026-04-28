"""SwarmSPX Scheduler — automated cron-style runs with Telegram output.

Schedule:
  8:00 AM ET  — Morning briefing (pre-market outlook)
  9:35 AM ET  — Opening signal (first candle settled)
  11:30 AM ET — Midday signal
  2:00 PM ET  — Afternoon signal (lotto mode)
  3:45 PM ET  — Close signal + outcome resolution + daily summary

All output goes to Telegram. No web dashboard dependency.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time as dtime
from typing import Optional

from swarmspx.clock import now_et
from swarmspx.engine import SwarmSPXEngine
from swarmspx.briefing import MorningBriefing
from swarmspx.events import EventBus
from swarmspx.alerts.dispatcher import AlertDispatcher
from swarmspx.alerts.telegram import send_telegram, _escape_md2

logger = logging.getLogger(__name__)

# Schedule in ET (Eastern Time) — hours and minutes
SCHEDULE = [
    (8, 0, "briefing"),     # Pre-market briefing
    (9, 35, "cycle"),       # Opening signal
    (11, 30, "cycle"),      # Midday signal
    (14, 0, "cycle"),       # Afternoon signal (lotto mode auto-activates)
    (15, 45, "cycle"),      # Close signal + outcomes
]


class SwarmScheduler:
    """Runs the swarm on a daily schedule, all output to Telegram."""

    def __init__(
        self,
        settings_path: str = "config/settings.yaml",
        timezone_offset: int = 0,
    ):
        self.settings_path = settings_path
        self.tz_offset = timezone_offset  # hours from ET (0 if server is ET)
        self._bus = EventBus()
        self._engine = SwarmSPXEngine(settings_path=settings_path, bus=self._bus)
        self._dispatcher = AlertDispatcher(bus=self._bus, min_confidence=0)
        self._briefing = MorningBriefing(self._engine.fetcher)
        self._ran_today: set[str] = set()

    async def run(self):
        """Main loop — checks schedule every 30 seconds."""
        logger.info("SwarmSPX Scheduler started. Schedule: %s",
                     ", ".join(f"{h}:{m:02d} {t}" for h, m, t in SCHEDULE))
        await send_telegram(
            f"\u2705 *SwarmSPX Scheduler Started*\n\n"
            f"Schedule \\(ET\\):\n"
            f"  08:00 \\- Morning Briefing\n"
            f"  09:35 \\- Opening Signal\n"
            f"  11:30 \\- Midday Signal\n"
            f"  14:00 \\- Afternoon Signal\n"
            f"  15:45 \\- Close \\+ Summary"
        )

        last_et_date = None
        while True:
            # ET-anchored clock — DST-aware, no manual offset needed.
            # Replaces the prior `now.hour + tz_offset` arithmetic which
            # produced wrong hours on UTC servers and silently fired nothing.
            now_et_dt = now_et()
            current_h = now_et_dt.hour
            current_m = now_et_dt.minute
            current_date = now_et_dt.date()

            # Reset ran_today at the ET day boundary (instead of relying on
            # hitting an exact 00:00 minute, which a long-running cycle could
            # easily skip and lock out the next day's schedule entirely).
            if last_et_date is not None and current_date != last_et_date:
                self._ran_today.clear()
            last_et_date = current_date

            # Check each scheduled slot
            for hour, minute, action in SCHEDULE:
                key = f"{hour}:{minute:02d}"
                if key in self._ran_today:
                    continue

                # Within the window (exact minute match)
                if current_h == hour and current_m == minute:
                    self._ran_today.add(key)
                    try:
                        if action == "briefing":
                            logger.info("Running morning briefing...")
                            await self._briefing.run()
                        elif action == "cycle":
                            logger.info("Running swarm cycle at %s...", key)
                            await self._run_cycle(key)
                    except Exception as e:
                        logger.error("Scheduled run %s failed: %s", key, e)
                        await send_telegram(
                            f"\u274c *Scheduled run failed*\n\n"
                            f"Time: {_escape_md2(key)}\n"
                            f"Error: {_escape_md2(str(e)[:200])}"
                        )

            await asyncio.sleep(30)

    async def _run_cycle(self, time_label: str):
        """Run a full swarm cycle and send results via Telegram."""
        trade_card = await self._engine.run_cycle()

        # The AlertDispatcher already handles sending trade cards
        # via Telegram when confidence threshold is met.
        # But if the cycle produced a WAIT, send a brief note.
        if trade_card and trade_card.get("action") == "WAIT":
            await send_telegram(
                f"\u23f8 *SwarmSPX {_escape_md2(time_label)}*\n\n"
                f"Signal: WAIT \\(no clear edge\\)\n"
                f"_{_escape_md2(trade_card.get('rationale', '')[:200])}_"
            )

        # At 3:45 PM, also send daily summary
        if time_label == "15:45":
            await self._send_daily_summary()

    async def _send_daily_summary(self):
        """Send end-of-day summary with win/loss stats."""
        stats = self._engine.db.get_signal_stats()
        signals = self._engine.db.get_recent_signals(limit=10)

        today_signals = [
            s for s in signals
            if s.get("timestamp") and
            datetime.fromisoformat(str(s["timestamp"])).date() == datetime.now().date()
        ]

        if not today_signals:
            return

        wins = sum(1 for s in today_signals if s.get("outcome") == "win")
        losses = sum(1 for s in today_signals if s.get("outcome") == "loss")
        pending = sum(1 for s in today_signals if s.get("outcome") == "pending")

        total_pnl = sum(
            float(s.get("outcome_pct", 0))
            for s in today_signals
            if s.get("outcome") in ("win", "loss")
        )

        pnl_str = f"{total_pnl:+.2f}%" if (wins + losses) > 0 else "N/A"
        pnl_emoji = "\U0001f7e2" if total_pnl > 0 else "\U0001f534" if total_pnl < 0 else "\u26aa"

        lines = [
            f"\U0001f4ca *SWARMSPX DAILY SUMMARY*",
            f"_{_escape_md2(datetime.now().strftime('%B %d, %Y'))}_",
            "",
            f"{pnl_emoji} *Day P&L:* {_escape_md2(pnl_str)}",
            f"*Signals:* {len(today_signals)} total",
            f"  \\- Wins: {wins}",
            f"  \\- Losses: {losses}",
            f"  \\- Pending: {pending}",
            "",
            f"*All\\-time:* {_escape_md2(str(round(stats.get('win_rate', 0))))}% win rate "
            f"\\({stats.get('total', 0)} signals\\)",
        ]

        await send_telegram("\n".join(lines))
