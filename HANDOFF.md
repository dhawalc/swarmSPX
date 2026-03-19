# SwarmSPX Overnight Sprint — Handoff Document

**Created**: 2026-03-18
**Context**: Mid-sprint handoff. Plan approved, Phase 0 complete, Phase 1 partially started.

---

## Sprint Plan

Full plan at: `~/.claude/plans/snug-gliding-russell.md`

**Goal**: Ship v1.1 + v1.2 + v3.0-lite overnight (~9 hours)

| Phase | Feature | Status |
|-------|---------|--------|
| **0** | Fix failing test + green baseline | DONE |
| **1** | v1.2 Outcome Tracking | DONE |
| **2** | v1.1 Real Options Chains | DONE |
| **3** | v3.0-lite Custom Agents | DONE |
| **4** | Polish, docs, final tests | DONE |

---

## What's Been Done

### Phase 0: Green Baseline (COMPLETE)
- Fixed `tests/test_agents.py`: renamed `test_forge_assigns_claude_cli_to_strategists` → `test_forge_assigns_premium_local_to_strategists`
- Updated assertions to match current config (phi4:14b, not Claude CLI)
- **44/44 tests pass**

### Phase 1a: DB Layer (COMPLETE)
- Modified `swarmspx/db.py`:
  - Added `spx_entry_price DOUBLE` and `memory_id VARCHAR` columns to `simulation_results` schema
  - `store_simulation_result()` now returns the inserted row ID via `RETURNING id`
  - Added `update_outcome(signal_id, outcome, outcome_pct)` method
  - Added `get_pending_signals(max_age_hours=24)` — returns unresolved signals
  - Added `get_recent_signals(limit=20)` — for dashboard display
  - Added `get_signal_stats()` — aggregate win rate, avg P&L, total/resolved/wins/losses

---

## What Remains

### Phase 1b: Outcome Tracker Service (NOT STARTED)
Create `swarmspx/tracking/__init__.py` (empty) and `swarmspx/tracking/outcome_tracker.py`:
- `OutcomeTracker` class with `check_pending_signals()` async method
- Fetches current SPX price, computes P&L for pending signals
- Resolution: WIN/LOSS/SCRATCH after 2h or EOD
- Calls `db.update_outcome()` and `memory.store_outcome()`
- Emits `OutcomeResolved` event

### Phase 1c: Wire into Engine (NOT STARTED)
Modify `swarmspx/engine.py`:
- Capture signal_id from `db.store_simulation_result()` (return value currently discarded at line 90)
- Capture memory_id from `memory.store_result()` (return value currently discarded at line 81)
- Pass `spx_entry_price` and `memory_id` to `store_simulation_result()`
- Create `OutcomeTracker` in `__init__`
- Call `tracker.check_pending_signals()` at end of `run_cycle()`

Modify `swarmspx/events.py`:
- Add `OutcomeResolved` event dataclass (signal_id, direction, outcome, outcome_pct)

Modify `swarmspx/alerts/dispatcher.py`:
- Import `OutcomeResolved`
- Add handler in `_handle()` for OutcomeResolved events
- Format and send to Telegram/Slack: "Signal resolved: WIN +1.2%"

### Phase 1d: Dashboard Integration (NOT STARTED)
Modify `swarmspx/web/routes.py`:
- Add `GET /api/signals` endpoint (calls `db.get_recent_signals()`)
- Add `GET /api/stats` endpoint (calls `db.get_signal_stats()`)

Modify `swarmspx/web/state.py`:
- Add `_on_outcome_resolved()` handler

Modify `swarmspx/web/static/index.html`:
- Add "Signal History" panel — table with direction, confidence, entry, outcome, P&L

### Phase 1e: Tests (NOT STARTED)
Create `tests/test_tracking.py`:
- `test_outcome_tracker_resolves_old_signals()`
- `test_outcome_tracker_ignores_recent_signals()`
- `test_outcome_feeds_back_to_aoms()`

### Phase 2: v1.1 Real Options Chains (NOT STARTED)
See sprint plan for full details. Summary:
- Create `swarmspx/ingest/tradier.py` — Tradier API client (httpx, async)
- Create `swarmspx/ingest/options.py` — OptionContract dataclass, OptionsSnapshot, select_strikes()
- Modify `swarmspx/ingest/market_data.py` — integrate Tradier, replace hardcoded put_call_ratio
- Modify `swarmspx/agents/base.py` — add OPTIONS DATA section to prompts
- Modify `swarmspx/report/generator.py` — add Greeks to synthesis prompt
- Modify alerts formatters — add Greeks fields
- Create `tests/test_tradier.py`

### Phase 3: v3.0-lite Custom Agents (NOT STARTED)
- Create `config/custom_agents.yaml` — example template
- Modify `swarmspx/agents/forge.py` — merge custom agents, cap at 30
- Modify `swarmspx/web/routes.py` — POST/DELETE /api/agents/custom
- Create `tests/test_custom_agents.py`

### Phase 4: Polish (NOT STARTED)
- Full test suite run
- Smoke tests (CLI, web)
- Update ROADMAP.md, README.md
- Final commits

---

## Key Files Reference

| File | Role |
|------|------|
| `swarmspx/db.py` | DuckDB persistence — JUST MODIFIED (new methods) |
| `swarmspx/engine.py` | Main orchestrator — needs outcome tracker wiring |
| `swarmspx/events.py` | Event definitions — needs OutcomeResolved |
| `swarmspx/memory.py` | AOMS integration — `store_outcome()` already exists (line 77) |
| `swarmspx/alerts/dispatcher.py` | Alert routing — needs OutcomeResolved handler |
| `swarmspx/web/routes.py` | REST API — needs /api/signals, /api/stats |
| `swarmspx/web/state.py` | Cycle state tracker — needs outcome handler |
| `swarmspx/ingest/market_data.py` | Market data — `put_call_ratio` hardcoded to 1.0 (line 51) |
| `swarmspx/agents/base.py` | Agent prompts — `_build_prompt()` needs OPTIONS DATA |
| `swarmspx/agents/forge.py` | Agent factory — needs custom agent merge |
| `swarmspx/report/generator.py` | Trade card synthesis — needs Greeks in prompt |
| `config/settings.yaml` | Model routing config |
| `config/agents.yaml` | 24 agent personas |

## Current Git State
- Branch: `main`
- 2 files modified (uncommitted): `swarmspx/db.py`, `tests/test_agents.py`
- Tests: 44/44 passing

## Important Notes
- All Ollama models run locally on RTX 4090
- Strategists use phi4:14b (NOT Claude CLI — switched in commit 058932c)
- AOMS at localhost:9100 is optional (graceful degradation)
- Tradier API key goes in `.env` as `TRADIER_API_KEY`
- Use sandbox URL: `https://sandbox.tradier.com/v1`
- No new pip dependencies needed — httpx handles all HTTP

## How to Resume
```bash
cd ~/Projects/swarmspx
source .venv/bin/activate
pytest tests/ -q  # verify 44/44 pass
# Then continue from Phase 1b (outcome tracker service)
```
