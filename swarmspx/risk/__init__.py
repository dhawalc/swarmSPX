"""Risk subsystem — pre-trade gate, position sizing, kill switch.

Modules:
    gate         — synchronous pre-trade check (daily/weekly loss bands,
                   position concentration, data freshness, idempotency).
    sizer        — Kelly fractional position sizing with daily lock.
    killswitch   — multi-trigger circuit breakers (daily 3% / weekly 6% /
                   monthly 10% / consecutive-loss / manual).
"""
