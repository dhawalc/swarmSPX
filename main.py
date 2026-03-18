#!/usr/bin/env python3
"""Run a single SwarmSPX simulation cycle."""
import asyncio
from swarmspx.engine import SwarmSPXEngine

async def main():
    engine = SwarmSPXEngine()
    await engine.run_cycle()

if __name__ == "__main__":
    asyncio.run(main())
