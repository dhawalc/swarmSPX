#!/usr/bin/env python3
"""SwarmSPX CLI - unified entry point for all modes."""
import argparse
import asyncio
import sys
from dotenv import load_dotenv
load_dotenv()


def main():
    parser = argparse.ArgumentParser(
        prog="swarmspx",
        description="SwarmSPX - 24-agent trading swarm intelligence engine",
    )
    parser.add_argument("--config", default="config/settings.yaml", help="Path to settings.yaml")

    sub = parser.add_subparsers(dest="command", help="Mode to run")

    # run: headless single cycle (Rich console output)
    run_p = sub.add_parser("run", help="Run a single simulation cycle (Rich console)")
    run_p.add_argument("--loop", action="store_true", help="Run continuously on schedule")

    # tui: full-screen Textual terminal UI
    sub.add_parser("tui", help="Launch interactive Textual terminal dashboard")

    # web: FastAPI web dashboard
    web_p = sub.add_parser("web", help="Launch web dashboard")
    web_p.add_argument("--host", default="0.0.0.0", help="Host to bind")
    web_p.add_argument("--port", type=int, default=8420, help="Port to serve on")

    # schedule: automated cron-style runs (all output to Telegram)
    sched_p = sub.add_parser("schedule", help="Run automated daily schedule (Telegram output)")
    sched_p.add_argument("--tz-offset", type=int, default=0,
                         help="Hours offset from ET (0 if server is ET)")

    # briefing: one-off morning briefing
    sub.add_parser("briefing", help="Send a morning briefing to Telegram (one-off)")

    # risk-status: print kill switch + sizing lock + recent gate decisions
    sub.add_parser("risk-status", help="Print risk subsystem state (kill switch + sizing cap + recent gates)")

    # risk-trip: manually trip the kill switch
    trip_p = sub.add_parser("risk-trip", help="Manually trip the kill switch")
    trip_p.add_argument("--reason", required=True, help="Human-readable reason")

    # risk-reset: clear the kill switch
    reset_p = sub.add_parser("risk-reset", help="Reset (clear) the kill switch")
    reset_p.add_argument("--by", default="cli", help="Who is resetting (audit log)")

    args = parser.parse_args()

    if args.command == "run":
        _run_cli(args)
    elif args.command == "tui":
        _run_tui(args)
    elif args.command == "web":
        _run_web(args)
    elif args.command == "schedule":
        _run_schedule(args)
    elif args.command == "briefing":
        _run_briefing(args)
    elif args.command == "risk-status":
        _run_risk_status(args)
    elif args.command == "risk-trip":
        _run_risk_trip(args)
    elif args.command == "risk-reset":
        _run_risk_reset(args)
    else:
        parser.print_help()
        sys.exit(1)


def _run_cli(args):
    from swarmspx.events import EventBus
    from swarmspx.engine import SwarmSPXEngine
    from swarmspx.ui.dashboard import RichConsoleSubscriber, console
    import yaml

    bus = EventBus()
    RichConsoleSubscriber(bus)
    engine = SwarmSPXEngine(settings_path=args.config, bus=bus)

    async def _loop():
        with open(args.config) as f:
            settings = yaml.safe_load(f)
        interval = settings["simulation"]["cycle_interval_sec"]
        console.print(f"[bold green]SwarmSPX running every {interval // 60}min[/bold green]")
        while True:
            try:
                await engine.run_cycle()
            except KeyboardInterrupt:
                break
            except Exception as e:
                console.print(f"[red]Cycle error: {e}[/red]")
            console.print(f"[dim]Next cycle in {interval}s...[/dim]")
            await asyncio.sleep(interval)

    async def _single():
        await engine.run_cycle()

    asyncio.run(_loop() if args.loop else _single())


def _run_tui(args):
    from swarmspx.events import EventBus
    from swarmspx.engine import SwarmSPXEngine
    from swarmspx.ui.tui.app import SwarmSPXApp

    bus = EventBus()
    engine = SwarmSPXEngine(settings_path=args.config, bus=bus)
    app = SwarmSPXApp(bus=bus, engine=engine)
    app.run()


def _run_web(args):
    import uvicorn
    from swarmspx.events import EventBus
    from swarmspx.engine import SwarmSPXEngine
    from swarmspx.web.app import create_app

    bus = EventBus()
    engine = SwarmSPXEngine(settings_path=args.config, bus=bus)
    app = create_app(bus=bus, engine=engine, settings_path=args.config)
    uvicorn.run(app, host=args.host, port=args.port)


def _run_schedule(args):
    from swarmspx.scheduler import SwarmScheduler
    scheduler = SwarmScheduler(
        settings_path=args.config,
        timezone_offset=getattr(args, "tz_offset", 0),
    )
    print(f"SwarmSPX Scheduler starting (tz_offset={getattr(args, 'tz_offset', 0)}h from ET)...")
    print("Schedule: 8:00 briefing, 9:35/11:30/14:00/15:45 cycles")
    print("All output → Telegram. Press Ctrl+C to stop.")
    asyncio.run(scheduler.run())


def _run_briefing(args):
    from swarmspx.ingest.market_data import MarketDataFetcher
    from swarmspx.briefing import MorningBriefing

    fetcher = MarketDataFetcher()
    briefing = MorningBriefing(fetcher)

    async def _send():
        result = await briefing.run()
        print("Briefing sent to Telegram:")
        for k, v in result.items():
            if k != "strategy_recommendation":
                print(f"  {k}: {v}")
            else:
                for sk, sv in v.items():
                    print(f"    {sk}: {sv}")

    asyncio.run(_send())


# ── Risk subsystem CLI helpers ───────────────────────────────────────────────

def _load_risk_components(config_path: str):
    """Build KillSwitch + Kelly sizer + DB without booting agents/Ollama.

    Used by risk-status / risk-trip / risk-reset to inspect or mutate state
    without paying the LLM-bootstrap cost.
    """
    import yaml

    from swarmspx.db import Database
    from swarmspx.risk.gate import PreTradeRiskGate
    from swarmspx.risk.killswitch import KillSwitch
    from swarmspx.risk.sizer import KellyPositionSizer

    with open(config_path) as f:
        settings = yaml.safe_load(f)
    risk_cfg = settings.get("risk", {}) or {}

    db = Database(settings["database"]["path"])
    db.init_schema()
    killswitch = KillSwitch(
        state_path=risk_cfg.get("killswitch_state_path", "data/killswitch_state.json"),
        daily_loss_pct=risk_cfg.get("daily_loss_pct", 3.0),
        weekly_loss_pct=risk_cfg.get("weekly_loss_pct", 6.0),
        monthly_loss_pct=risk_cfg.get("monthly_loss_pct", 10.0),
        max_consecutive_losses=risk_cfg.get("max_consecutive_losses", 3),
    )
    sizer = KellyPositionSizer(
        bankroll_usd=risk_cfg.get("bankroll_usd", 25_000.0),
        kelly_fraction=risk_cfg.get("kelly_fraction", 0.10),
        win_prob=risk_cfg.get("win_prob", 0.40),
        payoff_ratio=risk_cfg.get("payoff_ratio", 3.0),
        max_per_trade_pct=risk_cfg.get("max_per_trade_pct", 0.05),
        lock_dir=risk_cfg.get("lock_dir", "data"),
    )
    gate = PreTradeRiskGate(db=db)
    return db, killswitch, sizer, gate


def _run_risk_status(args):
    """Print human-readable snapshot of the risk subsystem."""
    db, killswitch, sizer, _gate = _load_risk_components(args.config)

    print("═══════════════════════════════════════════════════════════")
    print(" SwarmSPX RISK STATUS")
    print("═══════════════════════════════════════════════════════════")

    # Kill switch
    ks_state = killswitch.state
    icon = "🚨 TRIPPED" if ks_state.get("tripped") else "✅ CLEAR"
    print(f"\nKILL SWITCH: {icon}")
    if ks_state.get("tripped"):
        print(f"  Trigger:        {ks_state.get('triggered_by')}")
        print(f"  Reason:         {ks_state.get('triggered_reason')}")
        print(f"  Triggered at:   {ks_state.get('triggered_at')}")
        print(f"  Auto-clear at:  {ks_state.get('auto_clear_at') or 'manual only'}")
    print(f"  Lifetime trips: {ks_state.get('trigger_count', 0)}")

    # Sizing cap
    cap = sizer.get_today_cap()
    print(f"\nSIZING (locked for {cap.get('date')}):")
    print(f"  Bankroll:        ${cap.get('bankroll'):,.2f}")
    print(f"  Kelly fraction:  {cap.get('kelly_fraction'):.4f}  (raw {cap.get('raw_kelly'):.4f})")
    print(f"  Max per trade:   ${cap.get('max_per_trade_usd'):,.2f}  ({cap.get('max_per_trade_pct')*100:.2f}%)")

    # Recent gate decisions (last 20 signals' outcomes)
    print(f"\nRECENT SIGNALS (last 20):")
    try:
        signals = db.get_recent_signals(limit=20)
    except Exception as e:
        print(f"  (failed to read DB: {e})")
        signals = []
    if not signals:
        print("  (none)")
    else:
        # Aggregate by outcome
        from collections import Counter
        counts = Counter(s.get("outcome", "?") for s in signals)
        for outcome, n in counts.most_common():
            print(f"  {outcome:10s} {n}")

    # Stats
    try:
        stats = db.get_signal_stats()
        print(f"\nALL-TIME:")
        print(f"  Total signals:  {stats.get('total', 0)}")
        print(f"  Resolved:       {stats.get('resolved', 0)}")
        print(f"  Win rate:       {stats.get('win_rate', 0):.1f}%")
        print(f"  Avg P&L:        {stats.get('avg_pnl', 0):.2f}%")
    except Exception as e:
        print(f"  (failed to read stats: {e})")

    print()


def _run_risk_trip(args):
    """Manually trip the kill switch."""
    _db, killswitch, _sizer, _gate = _load_risk_components(args.config)
    killswitch.trip("manual", args.reason)
    print(f"Kill switch TRIPPED — reason: {args.reason}")


def _run_risk_reset(args):
    """Manually clear the kill switch."""
    _db, killswitch, _sizer, _gate = _load_risk_components(args.config)
    if not killswitch.is_tripped():
        print("Kill switch already CLEAR — nothing to reset.")
        return
    killswitch.reset(by=args.by)
    print(f"Kill switch RESET by {args.by}")


if __name__ == "__main__":
    main()
