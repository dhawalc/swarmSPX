#!/usr/bin/env python3
"""SwarmSPX CLI - unified entry point for all modes."""
import argparse
import asyncio
import sys


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

    args = parser.parse_args()

    if args.command == "run":
        _run_cli(args)
    elif args.command == "tui":
        _run_tui(args)
    elif args.command == "web":
        _run_web(args)
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


if __name__ == "__main__":
    main()
