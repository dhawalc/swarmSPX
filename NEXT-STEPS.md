# SwarmSPX — Next Steps Handoff

**Session ended:** 2026-04-28 (UTC)
**Tests:** 268/268 passing
**Working tree:** clean after the session's commits
**Auto-resume routine:** scheduled — fires daily at 04:00 PT (`trig_01TURSvF7MBk9FmRmNjAgEGf`) — manage at https://claude.ai/code/routines/trig_01TURSvF7MBk9FmRmNjAgEGf

---

## What got shipped this session

### War room (read first)
A 7-specialist war room produced a 6-month battle plan, plus a 13-CRITICAL / 17-HIGH code review.

- `.review/00-SUMMARY.md` — code review master summary
- `.review/warroom/00-BATTLE-PLAN.md` — master 6-month plan + 12 highest-conviction moves + 3 novel bets + decision gates
- `.review/warroom/01-quant.md` through `07-data.md` — per-specialist briefs

### Tier 0 — critical bug fixes (all from review)

| # | Fix | File(s) |
|---|---|---|
| 1 | Agent ID mismatch `put_call_pete` → `putcall_pete` (the agent never got ELO updates in production) | `swarmspx/scoring.py`, `swarmspx/web/static/js/leaderboard.js` |
| 2 | Wrap `engine.run_cycle` in try/except/finally + add concurrency lock | `swarmspx/engine.py` |
| 3 | ELO floor renormalization no longer drifts below `MIN_WEIGHT` (greedy one-shot algorithm) | `swarmspx/scoring.py` (new `_apply_floor` helper) |
| 4 | NEUTRAL votes no longer get penalized on every resolved signal | `swarmspx/scoring.py` |
| 5 | Outcome+ELO atomicity — ELO sync now runs BEFORE `update_outcome` so a crash mid-resolution preserves ELO | `swarmspx/tracking/outcome_tracker.py` |
| 6 | **Option P&L tracking** (THE biggest finding) — system now records `entry_premium`, `option_strike`, `option_type` at signal time, captures `exit_premium` at resolution, and computes outcome from premium delta NOT SPX move. Falls back to SPX-based for legacy signals. | `swarmspx/db.py` schema + `swarmspx/engine.py` + `swarmspx/ingest/market_data.py` `lookup_option_premium()` + `swarmspx/tracking/outcome_tracker.py` `_resolve_outcome()` |
| 7 | AOMemory rewritten as async `httpx.AsyncClient` (was blocking the event loop with sync httpx.post inside agent batches) | `swarmspx/memory.py` (full rewrite) + callsite awaits |
| 8 | ET-anchored time everywhere (was naive `datetime.now()` — UTC server would misroute every morning trade to lotto mode) | new `swarmspx/clock.py`, wired into `selector.py`, `market_data.py`, `scheduler.py` |

### Tier 1 — spine modules (Battle Plan §5–§7)

| Module | What |
|---|---|
| `swarmspx/risk/gate.py` | Pre-trade risk gate. Synchronous, ~50ms budget. Checks: kill switch, daily/weekly/monthly loss bands, consecutive losses, position count, data freshness, idempotency, direction validity. |
| `swarmspx/risk/sizer.py` | Kelly position sizer with daily lock. 0.10 Kelly default. Lock written to `data/sizing_lock_YYYY-MM-DD.json` at first call of the ET day, then immutable. |
| `swarmspx/risk/killswitch.py` | Multi-trigger circuit breaker. Persisted state in `data/killswitch_state.json`. Auto-clear semantics for daily-loss / consecutive-loss / data-quality; manual-only for weekly / monthly / explicit-manual. |
| `swarmspx/dealer/gex.py` | DIY GEX engine. Computes per-strike dealer gamma + net GEX + gamma flip + call/put walls from any option chain with OI + gamma. Replaces $199/mo SpotGamma. |
| `swarmspx/backtest/replay.py` | Honest event-driven backtester scaffold. EventReplayer (raises NotImplementedError until Polygon wiring), SimClock with PIT correctness, HalfSpreadPlusImpactSlippage model, `compute_metrics` for Sharpe/Sortino/MaxDD/Calmar, walk-forward window generator. |

### Tests (all new)
- `tests/test_clock.py` — 22 tests; ET correctness incl. DST
- `tests/test_risk.py` — 17 tests across gate / sizer / kill switch
- `tests/test_gex.py` — 13 tests on GEX math + walls + flip
- `tests/test_backtest_replay.py` — 17 tests on metrics + slippage + walk-forward

### Existing test rewrites
- `tests/test_memory.py` — converted to async to match the new `AOMemory` API; added failure-mode tests

---

## What's NOT done (next session priorities)

**Tier 1 wiring** — modules exist but aren't yet plugged into the cycle:

1. **Wire `PreTradeRiskGate` into `engine.run_cycle()`** — between trade-card generation and alert dispatch. If gate rejects, log + skip Telegram. ~30 min.
2. **Wire `KellyPositionSizer.size_for_signal()`** to inject `contracts` + `risk_usd` into the trade card. ~30 min.
3. **Wire `KillSwitch.is_tripped()`** into the cycle entry point. ~15 min.
4. **Inject `compute_gex(...)` into `market_context`** before agents see it. Update `agents/base.py` prompt template to include the GEX block. ~1h.
5. **Selector should consult GEX regime** — gamma-flip-aware strategy selection. ~1h.

**Tier 1 rest:**

6. **Polygon historical wiring for the backtester** — implement `EventReplayer.stream()`. Subscribe to Polygon Options Advanced ($199/mo) or Tradier historical. Replay 12 months of SPX through the pipeline. Compute honest Sharpe.
7. **Walk-forward execution** — orchestrate `generate_walk_forward_windows` over the historical dataset.

**Tier 2 (ML edge — only after honest backtester proves Sharpe > 1.0):**

8. **News→IV pipeline** — Haiku 4.5 scoring of headlines, predict 60s ATM IV change.
9. **LightGBM directional model** with isotonic + conformal calibration.
10. **Repurpose LLM swarm** — stop voting on direction; have agents parse FOMC/news/earnings into structured features.

---

## How to resume

```bash
cd ~/Projects/swarmspx
source .venv/bin/activate
pytest tests/ -q                # verify 268/268
git status                       # clean
git log --oneline -15
```

Then read `.review/warroom/00-BATTLE-PLAN.md` for the full plan and pick the next un-done item.

---

## Decision gates (don't skip — be ruthless)

- **End of Month 1 (~ May 28):** Polygon historical wired; honest Sharpe number computed.
- **End of Month 2:** if walk-forward Sharpe < 1.0 across ≥60% of test windows → pivot to single-name 0DTE OR monetize the framework as SaaS. Do NOT proceed to live execution.
- **End of Month 5:** if 30-day paper P&L (after slippage) < SPY return → do NOT fund with real money.
- **End of Month 6:** decision — live trading at 1×, OR pivot, OR shutdown.

---

## Caveats / open trade-offs

1. **Atomic outcome+ELO** — pragmatic fix reorders ELO before `update_outcome`. A crash between them now causes potential double-credit (was: permanent ELO loss). Future: add a `scored` BOOLEAN column to `simulation_results` and use a single transaction.
2. **`tz_offset` arg in `SwarmScheduler`** is now a no-op (kept for backwards compat). Remove in next major.
3. **Kelly sizer + risk gate are not yet wired** to the cycle. They exist as standalone modules. See "What's NOT done" #1–3.
4. **GEX engine not yet injected into agent prompts.** The math + dataclass are tested; wiring is next session.
5. **Backtester is a scaffold.** `EventReplayer.stream()` raises `NotImplementedError` by design — fails loudly until real data wiring lands.
6. **Throw away current ELO data.** Once option-P&L tracking is recording on live cycles, the existing ELO scores in the DB are noise (trained on the wrong signal). Consider a one-time DB reset on `agent_elo_scores` after the next 30 days of clean data.

---

## How the auto-resume routine reads this

The cron (4 AM PT daily) clones `https://github.com/dhawalc/swarmSPX`, reads `.review/warroom/00-BATTLE-PLAN.md` and this file, picks the next un-done task, implements it end-to-end with tests, runs `pytest tests/ -q`, commits, writes a `.review/auto-resume-YYYY-MM-DD.md` report, and pushes. It will NOT touch broker creds, .env files, or live-trade code. Disable via https://claude.ai/code/routines/trig_01TURSvF7MBk9FmRmNjAgEGf.
