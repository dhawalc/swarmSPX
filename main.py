#!/usr/bin/env python3
"""Run a single SwarmSPX simulation cycle."""
import asyncio
from swarmspx.events import EventBus
from swarmspx.engine import SwarmSPXEngine
from swarmspx.ui.dashboard import RichConsoleSubscriber

async def main():
    bus = EventBus()
    RichConsoleSubscriber(bus)
    engine = SwarmSPXEngine(bus=bus)
    await engine.run_cycle()

if __name__ == "__main__":
    asyncio.run(main())
