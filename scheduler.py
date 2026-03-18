#!/usr/bin/env python3
"""Run SwarmSPX on a 5-minute schedule during market hours."""
import asyncio
import yaml
from swarmspx.engine import SwarmSPXEngine
from swarmspx.ui.dashboard import console

async def main():
    with open("config/settings.yaml") as f:
        settings = yaml.safe_load(f)
    interval = settings["simulation"]["cycle_interval_sec"]

    console.print(f"[bold green]SwarmSPX Scheduler started -- running every {interval//60}min[/bold green]")
    engine = SwarmSPXEngine()

    while True:
        try:
            await engine.run_cycle()
        except KeyboardInterrupt:
            console.print("[bold red]Shutting down...[/bold red]")
            break
        except Exception as e:
            console.print(f"[red]Cycle error: {e}[/red]")
        console.print(f"[dim]Next cycle in {interval}s...[/dim]")
        await asyncio.sleep(interval)

if __name__ == "__main__":
    asyncio.run(main())
