# SwarmSPX Code Review — Synthesis

**Verdict: Do NOT rebuild. The architecture is sound.** But there are **13 CRITICAL** and **17+ HIGH** issues that need fixing before this trades real money or runs on a public host. The most important finding: the **Darwinian feedback loop is training agents on the wrong signal** — ELO is rewarding agents based on whether SPX moved, not whether the *option trade* would have profited.

This is fixable in 2-3 days of focused work, not a rewrite.

---

## CRITICAL — fix before next live cycle

### 1. OutcomeTracker measures equity, not option P&L  *(03-data-strategy)*
Resolution compares SPX entry vs SPX exit prices. A 0.3% SPX move records as "scratch" even though a 0DTE option could have gained 70%+. **Every ELO score and backtest result is being trained on the wrong signal.**

### 2. ELO floor renormalization never converges  *(scoring.py:278-283)*
`MIN_WEIGHT=0.02` is a soft floor. With realistic ELO spread the iterative loop exits with weights still ~0.00005 below the floor. The backtest engine uses correct one-shot math; production does not.

### 3. NEUTRAL votes always penalized  *(scoring.py:377)*
`correct_direction` is always BULL or BEAR after a resolution. Any agent that votes NEUTRAL is marked wrong on **every** resolved signal — both wins and losses. Hedgers get permanently crushed.

### 4. Agent ID mismatch: `put_call_pete` vs `putcall_pete`
Three places disagree: `scoring.py` (`put_call_pete`), `backtest/engine.py` (`putcall_pete`), `agent_network.js` (`putcall_pete`). One agent never gets ELO updates in production. Leaderboard hover badge always misses for that node.

### 5. ELO crash window  *(outcome_tracker.py vs scoring.py:398)*
`db.update_outcome()` runs before `_sync_to_db()`. A crash between them marks the signal resolved (no longer pending) but loses the ELO update permanently. Every restart drops a batch.

### 6. Sync `httpx.post()` in AOMemory blocks the event loop  *(memory.py)*
Called from inside `pit._run_round()` for every agent. Up to 5s blocking per call × ~24 calls per cycle. Freezes WebSocket pushes and the FastAPI server.

### 7. `engine.run_cycle()` has zero exception handling
Fired via `asyncio.ensure_future` with no try/except. Any error after `CycleStarted` emits leaves status locked at `"running"` until restart. The `/cycle/trigger` guard is then permanently blocked.

### 8. Naive `datetime.now()` for session detection  *(selector.py + market_data.py)*
On a UTC server (any standard VPS), "morning" ends at 07:30 UTC = 3:30 AM ET, "afternoon" starts before market opens. Every morning trade misroutes to lotto mode.

### 9. Schema migration swallows all exceptions  *(db.py)*
`try/except Exception` no-ops on transient errors. Startup state can corrupt with no log.

### 10. TOCTOU race on `POST /api/cycle/trigger`  *(routes.py:76-81)*
Status check is not synchronously coupled to the state mutation. Two requests pass the check, two cycles run concurrently, agents share `last_vote` state.

### 11. `/api/backtest` blocks event loop  *(routes.py:112-181)*
10k-iteration loop with no `await`. Stalls all WS broadcasts for 2-15s. Move to `run_in_executor`.

### 12. No auth, default bind `0.0.0.0`  *(cli.py:29)*
Anyone on LAN can trigger cycles, inject custom agents, delete agents. Default to `127.0.0.1` and add a token.

### 13. WebSocket broadcast sequential, no per-client timeout  *(ws_manager.py:78-87)*
One stuck client stalls all others. Use `asyncio.gather` with `wait_for(..., timeout=5)`.

---

## HIGH — fix this week

| # | Issue | File |
|---|-------|------|
| H1 | "+4-6% improvement" backtest claim is circular — synthetic accuracies baked in, then "discovered" | backtest/engine.py |
| H2 | `conviction_threshold: 70` in settings.yaml is dead config (zero usages) | settings.yaml |
| H3 | Claude CLI subprocess leaks zombie on timeout (`proc.kill()` without `await proc.wait()`) | claude_client.py |
| H4 | Engine-level cycle re-entrancy (separate from #10) — needs `asyncio.Lock` | engine.py |
| H5 | All AOMS exception handlers swallow silently with no logging | memory.py |
| H6 | DuckDB write-write deadlock potential under contention | db.py |
| H7 | Schwab 401 → infinite retry loop on persistent expiry | ingest/schwab.py |
| H8 | `enrich_with_options` makes blocking sync HTTP calls inside `async` method | ingest/market_data.py |
| H9 | No rate limiting against Schwab's 120 req/min cap | ingest/schwab.py |
| H10 | "VWAP" is actually `(H+L+C)/3` typical price — off by up to 29 SPX points | ingest/market_data.py |
| H11 | TOCTOU in `upsert_agent_score` | db.py |
| H12 | Scheduler `now.hour + tz_offset` can produce hour > 24 or < 0 | scheduler.py |
| H13 | Scheduler midnight reset can be missed if a cycle runs long → entire next day skipped | scheduler.py |
| H14 | `_escape_md2` omits `\` from escape set → some Telegram messages drop | alerts/telegram.py |
| H15 | Slack Block Kit `header` block type is invalid inside `attachments[]` | alerts/slack.py |
| H16 | Alert dispatcher `_listen` loop dies permanently on any handler exception | alerts/dispatcher.py |
| H17 | Daily summary `limit=10` silently truncates if >10 signals today | scheduler.py |
| H18 | Per-frame `shadowBlur` at 13+ call sites in agent_network.js — fine on 4090, drops frames on mobile | js/agent_network.js |
| H19 | New ELO badge renders `ELO NaN` before first leaderboard fetch (`elo ?` should be `elo != null ?`) | js/agent_network.js |

---

## Recommended fix order (1 week)

**Day 1 — Stop the bleeding**
- #1 OutcomeTracker option-P&L  ← biggest payoff
- #4 agent-id rename (15 min, blocks several downstream issues)
- #2, #3 ELO math fixes
- #5 atomic outcome+ELO transaction

**Day 2 — Async correctness**
- #6 AsyncClient for AOMS
- #7 wrap run_cycle in try/finally with always-emit CycleCompleted
- H4 engine `asyncio.Lock`
- H8 async Schwab options call
- H16 dispatcher loop guard

**Day 3 — Time + auth**
- #8, H12, H13 timezone-aware scheduling (use `pytz` + ET)
- #12 bind 127.0.0.1 + token auth
- #10, #11 trigger race + backtest off-loop

**Day 4 — Polish**
- All HIGH frontend fixes
- Telegram/Slack format fixes
- Honest backtest (real historical data, not synthetic)

---

## What to leave alone

- Overall pipeline shape (engine → pit → consensus → strategy → report → alert) is clean.
- DuckDB choice is fine for a local agent.
- ELO + softmax is a reasonable scoring approach (the math just needs the bug fixes).
- Vanilla canvas frontend is well-isolated and has no XSS exposure.
- The 24-agent tribe structure works.
- Provider routing (Llama 8B + Phi-4 14B) is a sensible local-only design.

## What to consider rebuilding *later* (not now)

- **Backtest engine** — current one uses synthetic vote data with random accuracies. The "+4-6%" claim is not real evidence. Replace with replay over historical SPX bars + actual option chain snapshots before claiming any edge.
- **Memory module** — sync httpx is the proximate fix, but AOMS itself is single-server, optional, and undocumented. Consider whether you actually use it; if not, rip it out.
- **OutcomeTracker** — once #1 is fixed, the rest of the file is small enough to rewrite cleanly with proper option-P&L modeling.

Per-domain detail in `01-darwinian.md`, `02-pipeline.md`, `03-data-strategy.md`, `04-surfaces.md`, `05-frontend.md`.
