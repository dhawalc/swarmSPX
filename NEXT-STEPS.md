# SwarmSPX — Next Steps Handoff

**Session date:** 2026-04-28 (UTC)
**Tests:** 291/291 passing
**Commits this session:** 6 (all pushed to `origin/main`)
**Auto-resume routine:** `trig_01TURSvF7MBk9FmRmNjAgEGf` — daily at 04:00 PT — manage at https://claude.ai/code/routines/trig_01TURSvF7MBk9FmRmNjAgEGf

---

## Pipeline state (as of this commit)

```
   ┌──────────────────────────────────────────────────────────────────┐
   │  Cycle entry                                                      │
   │    └─► KillSwitch.is_tripped() → if YES, short-circuit           │
   │    └─► Fetch market + options chain                               │
   │    └─► compute_gex(...) → inject gex_block into market_context   │
   │    └─► Agents see GEX in their prompt (war room §7)              │
   │    └─► Pit runs N rounds of debate → consensus                   │
   │    └─► select_strategy() (GEX-aware: positive_gamma → IRON_CONDOR │
   │           override; negative_gamma + near wall → LOTTO override)  │
   │    └─► KellyPositionSizer.size_for_signal() with daily lock      │
   │    └─► Generate trade card                                        │
   │    └─► Inject sizing into trade card                              │
   │    └─► PreTradeRiskGate.check()                                   │
   │           PASS → emit TradeCardGenerated → AlertDispatcher fires │
   │           REJECT → log, persist outcome='gated', NO dispatch     │
   │    └─► Persist signal + agent votes + audit log JSONL            │
   │    └─► Open paper position (when paper_trading.enabled)          │
   │    └─► Resolve pending signals (option-P&L, NOT SPX move)        │
   │    └─► Auto-evaluate kill-switch loss bands                      │
   │    └─► Paper broker check_exits (target / stop / EOD)            │
   │  Cycle exit (CycleCompleted always emitted via try/finally)       │
   └──────────────────────────────────────────────────────────────────┘
```

Every box exists, is tested, and is wired into `engine.run_cycle`.

---

## What got shipped this session — 6 commits

### 1. `1553c52` — Tier 0 critical bug fixes
- Agent ID mismatch (`put_call_pete` → `putcall_pete`)
- `engine.run_cycle` wrapped in try/finally + asyncio.Lock
- ELO floor renormalization rewritten as one-shot greedy
- NEUTRAL votes no longer penalized on every resolution
- Outcome+ELO atomicity (ELO sync first, then mark resolved)
- Option P&L tracking (entry_premium / exit_premium / strike / type)
- AOMemory rewritten as async httpx.AsyncClient
- ET-anchored time everywhere via new `swarmspx/clock.py`

### 2. `8fbe775` — Tier 1 spine modules (standalone)
- `swarmspx/risk/gate.py` — pre-trade risk gate
- `swarmspx/risk/sizer.py` — Kelly sizer with daily lock
- `swarmspx/risk/killswitch.py` — multi-trigger circuit breaker
- `swarmspx/dealer/gex.py` — DIY GEX engine (replaces SpotGamma)
- `swarmspx/backtest/replay.py` — honest event-driven scaffold

### 3. `9992916` — War room + docs
- `.review/00-SUMMARY.md`, 5 per-domain code reviews
- `.review/warroom/00-BATTLE-PLAN.md`, 7 specialist briefs
- `NEXT-STEPS.md`

### 4. `e37781d` — Wire Tier 1 into engine.run_cycle
- KillSwitch checked at cycle entry
- compute_gex() injection (JSON-safe primitives only)
- Kelly sizing into trade card
- Risk gate fires before TradeCardGenerated; rejects → outcome='gated'
- Auto-evaluation of kill-switch loss bands at cycle end
- 4 integration tests in `tests/test_engine_wiring.py`

### 5. `012b35d` — Wave 2 (GEX-aware + audit + CLI + API)
- Selector consults `gex_regime` / `gamma_flip` / `call_wall` / `put_wall`
  - Positive gamma + low-mid confidence → IRON_CONDOR override
  - Negative gamma + price near wall → LOTTO override
- `swarmspx/audit.py` — per-decision JSONL log (data/decisions/YYYY-MM-DD.jsonl)
- CLI subcommands: `risk-status`, `risk-trip`, `risk-reset`
- `GET /api/risk`, `POST /api/risk/trip`, `POST /api/risk/reset`

### 6. `0216187` — Paper broker
- `swarmspx/paper.py` — full shadow trading simulator
- New DuckDB table `paper_positions`
- Auto-exit on target / stop / EOD via `check_exits(fetcher)`
- Wired into engine when `settings.paper_trading.enabled: true`
- 10 tests in `tests/test_paper.py`

---

## What's STILL NOT done — these need YOU

These cannot be built in code alone. They need data subscriptions, broker accounts, and calendar time.

### Tier 1: prove edge before going live

1. **Subscribe to Polygon Options Advanced** ($199/mo) — required for the
   honest backtester. Implement `EventReplayer.stream()` in
   `swarmspx/backtest/replay.py` using pyarrow.
2. **Run walk-forward on 12 months of SPX** with the new pipeline. The
   `compute_metrics(...)` function already returns Sharpe/Sortino/MaxDD/Calmar.
3. **Decision gate (war room):** if walk-forward Sharpe < 1.0 across ≥60%
   of test windows → pivot to single-name 0DTE OR monetize as SaaS. **Do
   NOT proceed to live execution.**

### Tier 2: enable paper trading + collect 30 days of data

4. **Enable paper trading** by adding to `config/settings.yaml`:
   ```yaml
   paper_trading:
     enabled: true
     target_multiplier: 2.0
     stop_multiplier: 0.5
   ```
5. **Run the scheduler for 30 days** with paper trading enabled. The
   `paper_positions` DuckDB table accumulates real data.
6. **Daily report:** `python -m swarmspx.cli risk-status` shows the
   running state. Inspect raw with `duckdb data/swarmspx.duckdb
   "SELECT * FROM paper_positions"`.

### Tier 3: extract more edge from the data we already have

7. **Subscribe to SpotGamma Standard** ($129/mo) OR keep the DIY GEX
   engine. The DIY math matches SqueezeMetrics; SpotGamma's only edge is
   ~50ms speed which is irrelevant for retail.
8. **Subscribe to Unusual Whales basic** ($48/mo) for sweep alerts and
   dark-pool prints — wire into agent prompts.
9. **News-to-IV pipeline** — Haiku 4.5 ($50/mo Anthropic budget) +
   NewsAPI ($99/mo). Score headlines, predict 60s ATM IV change. Trade
   long ATM straddles when predicted IV pop > +5% AND realized < ATM IV.

### Tier 4: when you're ready for real money (and not before)

10. **Broker setup** — Schwab production access (vs the current Schwab
    auth via `~/D2DT/backend/data/schwab_token.json`).
11. **Live execution wiring** — uncomment / enable real order submission.
    Currently the cycle stops at `TradeCardGenerated` → `AlertDispatcher`
    sends to Telegram only. Live execution would wrap the dispatcher path
    with idempotent client_order_id (already computed by the risk gate).
12. **Reconciliation loop** — every 5s compare broker positions vs local
    `paper_positions` (or its real-money sibling). Any drift → kill switch.
13. **Chaos test** — kill the VPS mid-cycle, verify recovery.
14. **30-day live execution at 0.1× normal size.** If positive
    expectancy, scale to 1×. If not, accept and pivot.

---

## Decision gates (don't skip)

| Gate | When | Pass criteria |
|------|------|---------------|
| **Backtest gate** | After Tier 1 (~Month 1) | OOS Sharpe > 1.0 across ≥60% of walk-forward windows |
| **Paper gate** | After 30 days of paper trading | Paper P&L (after slippage) > SPY return for the same window |
| **Live gate** | After 30 days at 0.1× live | Live P&L > paper P&L − 50bps (slippage envelope) |

If any gate fails, **do not advance**. Pivot or shutdown.

---

## How to run NOW

```bash
cd ~/Projects/swarmspx
source .venv/bin/activate

# Verify health
pytest tests/ -q                                # 291/291

# Operational
python -m swarmspx.cli risk-status              # state snapshot
python -m swarmspx.cli risk-trip --reason "X"   # manual halt
python -m swarmspx.cli risk-reset --by you      # clear

# Daemons
python -m swarmspx.cli web --port 8420          # dashboard at /api/risk + /api/leaderboard
python -m swarmspx.cli schedule                 # cron-style ET schedule, all output Telegram
python -m swarmspx.cli briefing                 # one-off pre-market briefing

# Inspect
duckdb data/swarmspx.duckdb "SELECT * FROM paper_positions ORDER BY opened_at DESC LIMIT 10"
duckdb data/swarmspx.duckdb "SELECT outcome, COUNT(*) FROM simulation_results GROUP BY outcome"
ls data/decisions/                              # one JSONL per ET date
```

---

## Caveats

1. **Gated signals double-credit window** — atomic outcome+ELO is partially
   solved. A crash between ELO sync and `update_outcome` causes potential
   double-credit. Mitigation: add a `scored` BOOLEAN column to
   `simulation_results` and use a single transaction.
2. **`tz_offset` arg in `SwarmScheduler`** is now a no-op (kept for
   backwards compat). Remove in next major.
3. **EventReplayer.stream() raises NotImplementedError** — by design.
   Fails loudly until Polygon historical data is wired.
4. **Throw away current ELO data** — once option-P&L is recording on live
   cycles, the existing scores are noise (trained on the wrong signal).
5. **No real backtest yet.** All claims about edge remain unproven. The
   "+4-6% Darwinian improvement" claim is circular per war room review H1.
   Strip from public marketing until backtest gate passes.
6. **Paper trading is OFF by default.** Enable explicitly in
   `config/settings.yaml` per the snippet in Tier 2.

---

## How the auto-resume routine reads this

The cron (4 AM PT daily) clones `https://github.com/dhawalc/swarmSPX`,
reads `.review/warroom/00-BATTLE-PLAN.md` and this file, picks the next
un-done task, implements it end-to-end with tests, runs `pytest tests/ -q`,
commits, writes `.review/auto-resume-YYYY-MM-DD.md`, and pushes. It
will NOT touch broker creds, .env files, or live-trade code.

Disable via https://claude.ai/code/routines/trig_01TURSvF7MBk9FmRmNjAgEGf.
