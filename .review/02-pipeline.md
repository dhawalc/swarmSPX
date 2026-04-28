# SwarmSPX Pipeline Code Review
**Reviewed:** 2026-04-27  
**Scope:** engine.py, simulation/pit.py, agents/base.py, agents/forge.py, providers.py, memory.py, events.py, report/generator.py, claude_client.py  
**Verdict:** BLOCK — 2 CRITICAL, 4 HIGH issues found

---

## Summary

The simulation pipeline is structurally sound and mostly Pythonic. The async gather pattern, exception-to-fallback-vote design in `think()`, and EventBus backpressure handling are all well-executed. However two critical runtime bugs exist: synchronous `httpx` calls inside the async event loop block the entire engine for up to 5 seconds on every AOMS round trip, and `engine.run_cycle()` has no top-level exception handler — any uncaught error in the happy path (e.g. a DuckDB write failure) turns into an unhandled asyncio task exception with the engine stuck in a non-idle state. Additionally, `conviction_threshold` in `settings.yaml` is dead config — it is never read by any Python file, which is a silent correctness bug. The Claude CLI subprocess leaks a zombie process on timeout. Several HIGH issues around re-entrancy, prompt key injection, and event loss round out the findings.

---

## CRITICAL

### C1 — Sync httpx Blocks the Async Event Loop
**Files:** `swarmspx/memory.py:16`, `memory.py:66`, `memory.py:80`, `simulation/pit.py:86`

**Issue:** `AOMemory` uses `httpx.post()` (synchronous) throughout. `memory.recall_for_agent()` is called in `pit._run_round()` inside the async event loop — once per agent per batch, serially, *before* the batch's `asyncio.gather`. With 24 agents across 4 batches × 3 rounds = 12 synchronous HTTP calls to AOMS, each up to 5 s. Under the 5 s timeout this can block the loop for up to 60 s, freezing all WebSocket pushes and the entire FastAPI server.

**Fix:** Replace `httpx` with `httpx.AsyncClient` and `await` all calls. Alternatively call `asyncio.to_thread(self.memory.recall_for_agent, ...)` at each call site. Also move `memory.store_result()` and `memory.recall()` in `engine.py:91,101` to `asyncio.to_thread`.

```python
# memory.py — replace sync client
async def recall(self, query: str, limit: int = 10, min_score: float = 0.6) -> list[dict]:
    async with httpx.AsyncClient(timeout=self.timeout) as client:
        response = await client.post(...)
```

---

### C2 — `engine.run_cycle()` Has No Top-Level Exception Guard
**File:** `swarmspx/engine.py:58-132`

**Issue:** `run_cycle` contains zero `try/except` blocks. It is launched via `asyncio.ensure_future(engine.run_cycle())` in the web route. Any uncaught exception in the happy path — a DuckDB write failure, a `KeyError` from a malformed consensus dict, a network error in `reporter.generate` not caught by its inner handler — propagates as an unhandled asyncio task exception. Python logs it to stderr but the engine is left with `CycleStarted` emitted and `CycleCompleted` never emitted, so `state.status` stays `"running"` and the trigger guard permanently blocks new cycles until the server restarts.

**Fix:** Wrap the entire body of `run_cycle` in `try/except Exception`:

```python
async def run_cycle(self) -> dict:
    self.cycle_count += 1
    start = time.time()
    await self.bus.emit(CycleStarted(cycle_id=self.cycle_count))
    try:
        # ... all existing logic ...
        return trade_card
    except Exception as exc:
        logger.exception("run_cycle failed: %s", exc)
        await self.bus.emit(EngineError(message=str(exc)))
        return {}
    finally:
        duration = time.time() - start
        await self.bus.emit(CycleCompleted(cycle_id=self.cycle_count, duration_sec=duration))
```

---

## HIGH

### H1 — `conviction_threshold: 70` Is Dead Config (Never Read)
**File:** `config/settings.yaml:53`, all `.py` files

**Issue:** `grep -rn "conviction_threshold"` across all Python source returns zero results. The setting exists in `settings.yaml` and is described as "min conviction % to include in consensus" but `ConsensusExtractor.extract()` never reads it. Agents with conviction 0–69 are included in every consensus computation. This is a silent correctness bug — the operator believes low-conviction agents are filtered but they are not.

**Fix:** Thread the setting into `TradingPit.__init__` → `ConsensusExtractor.extract()` and filter votes:

```python
# consensus.py extract()
if agent_weights is None:  # or always
    votes = [v for v in votes if v.conviction >= conviction_threshold]
    if not votes:
        return self._empty_consensus()
```

---

### H2 — Claude CLI Subprocess Leaks Zombie on Timeout
**File:** `swarmspx/claude_client.py:34-43`

**Issue:** On `asyncio.TimeoutError`, `proc.kill()` is called but `await proc.wait()` is never called. The child process becomes a zombie (retained in the OS process table until the parent exits). With 24 agents × 3 rounds and a potential mass-timeout scenario, this could exhaust process table slots. Additionally, if the `asyncio.wait_for` is cancelled from outside (e.g. test teardown), the `except asyncio.TimeoutError` branch is not reached and `proc` is never reaped.

**Fix:**
```python
except asyncio.TimeoutError:
    log.warning("claude CLI timed out after 120s")
    proc.kill()
    await proc.wait()   # reap the zombie
    return ""
```

---

### H3 — Race Condition in Trigger Guard (TOCTOU)
**File:** `swarmspx/web/routes.py:76-81`

**Issue:** The guard reads `state.get_snapshot()["status"]`, then calls `asyncio.ensure_future(engine.run_cycle())`. Between those two lines the status has not changed — `CycleStarted` has not been emitted and consumed by `CycleState` yet. If two HTTP requests arrive in the same asyncio turn (e.g. two rapid POSTs to `/api/cycle/trigger`), both pass the guard check, both launch `ensure_future`, and two cycles run concurrently. `TraderAgent.last_vote` is mutable instance state shared across cycles — concurrent cycles will corrupt round-over-round vote tracking.

**Fix:** Add an `asyncio.Lock` on the engine:

```python
# engine.py __init__:
self._lock = asyncio.Lock()

async def run_cycle(self) -> dict:
    if self._lock.locked():
        raise RuntimeError("Cycle already in progress")
    async with self._lock:
        ...
```

```python
# routes.py trigger_cycle:
if engine._lock.locked():
    raise HTTPException(status_code=409, detail="Cycle already in progress")
asyncio.ensure_future(engine.run_cycle())
```

---

### H4 — Silent Exception Swallowing in `memory.py`
**File:** `swarmspx/memory.py:25-26`, `74-75`, `96-97`

**Issue:** All three public methods swallow `Exception` silently — no `logger.warning`, no indication AOMS is down. In production, AOMS going down is invisible: `recall()` returns `[]`, `store_result()` returns `None`, `store_outcome()` returns nothing. The operator has no signal that memory persistence is broken. The `memory_id` stored in DuckDB becomes `None` for every signal while AOMS is down, silently corrupting the AOMS linkage for the entire downtime period.

**Fix:** Add logging at minimum:
```python
except Exception as exc:
    logger.warning("AOMS recall failed (degraded mode): %s", exc)
    return []
```

---

## MEDIUM

### M1 — Duplicate `if round_num > 1` Check in `_build_prompt`
**File:** `swarmspx/agents/base.py:90,95`

**Issue:** Line 90 already guards `if peers_votes and round_num > 1`. Line 95 re-checks `if round_num > 1` — redundant. No bug, but confusing to read.

**Fix:** Remove the inner `if round_num > 1:` on line 95 — it's dead.

---

### M2 — `vote_counts["BULL"]` Direct Access in `_build_prompt` (Minor KeyError Risk)
**File:** `swarmspx/agents/base.py:94`

**Issue:** `vote_counts` is pre-seeded with `{"BULL": 0, "BEAR": 0, "NEUTRAL": 0}` and then updated via `.get()`, so for standard directions this is safe. However if `peers_votes` contains a vote with a direction like `""` (empty string from a corrupt deserialization path) it would add a key not present in the seeded dict but the `vote_counts['BULL']` accesses on line 94 would still work. Low risk, but the seeded dict initialization and the `.get()` update are inconsistent — use `Counter` instead for clarity.

---

### M3 — Report Generator Direct Key Access on Market Context
**File:** `swarmspx/report/generator.py:114-116`

**Issue:** `market_context['spx_price']`, `market_context['vix_level']`, and `market_context['market_regime']` use direct dict access without `.get()`. The engine's entry guard checks `spx_price` truthy before calling `reporter.generate`, but `vix_level` and `market_regime` are not guarded. If `MarketDataFetcher` returns a snapshot missing `vix_level` (e.g. data provider outage), the report generator crashes with a `KeyError`, which propagates out of the generator's own `try/except` only because the `except Exception` block is around the LLM call, not the prompt-building f-string.

**Fix:** Use `.get()` with safe defaults in the f-string, matching the style used in `_build_prompt`.

---

### M4 — `aoms_memories` Parameter Type Annotation Is Wrong
**File:** `swarmspx/report/generator.py:96`

**Issue:** `aoms_memories: list[dict] = None` is flagged by mypy as `Incompatible default for parameter`. Should be `Optional[list[dict]] = None`. Same pattern in `db.py:286`. Neither causes a runtime failure but mypy reports them as errors.

---

### M5 — EventBus Callbacks Swallow All Exceptions Silently
**File:** `swarmspx/events.py:129-133`

**Issue:** Registered sync callbacks are wrapped in `except Exception: pass` with no logging. If an `AlertDispatcher` callback crashes (e.g. Telegram rate limit raises an exception), the failure is invisible. All events thereafter continue silently missing that callback.

**Fix:**
```python
for cb in self._callbacks:
    try:
        cb(event)
    except Exception as exc:
        log.warning("EventBus callback %s raised: %s", cb, exc)
```

---

## LOW

### L1 — `engine.py` Uses Relative Config Path `"config/settings.yaml"`
**File:** `swarmspx/engine.py:28`, `agents/forge.py:19`

**Issue:** `open("config/settings.yaml")` is relative to `cwd` at runtime, not relative to the file. This works when launched from the repo root but fails silently in tests or if the working directory differs. `forge.py` has the same issue with `config/agents.yaml` and `config/custom_agents.yaml`.

**Fix:** Use `Path(__file__).resolve().parents[N] / "config" / "settings.yaml"` as done correctly in `routes.py:18`.

---

### L2 — `cycle_count` Incremented Before Guard Check
**File:** `swarmspx/engine.py:60`

**Issue:** `self.cycle_count += 1` is the first line of `run_cycle`, before the market data check. If the cycle aborts early (`return {}`), the count still increments. The returned ID in the trigger response (`(snap.get("cycle_id") or 0) + 1`) will be misaligned with the actual emitted `cycle_id`.

---

### L3 — `forge.py` YAML Loading Without Schema Validation
**File:** `swarmspx/agents/forge.py:24`

**Issue:** `agents.yaml` is loaded with `yaml.safe_load` but not schema-validated. If `tribes` key is missing or agents list is malformed, `create_all()` raises `KeyError` or `TypeError` during engine startup. The error is not caught, so the entire app fails to start with no user-friendly message.

**Fix:** Validate the structure with a simple check after loading:
```python
if not isinstance(self.agent_config.get("tribes"), dict):
    raise ValueError("agents.yaml: 'tribes' key missing or not a dict")
```

---

### L4 — `resolve_model` Raises `ValueError` for Missing Env Var at Agent-Creation Time
**File:** `swarmspx/providers.py:35-39`

**Issue:** If `api_key_env` is set in `settings.yaml` but the env var is absent, `AgentForge.create_all()` raises `ValueError` during `SwarmSPXEngine.__init__`. This is correct behavior but the error message doesn't indicate which tribe or agent triggered it, making debugging harder.

---

## Verdict

**BLOCK — Fix C1 and C2 before production use.**

C1 (sync httpx in async loop) will cause periodic full-server hangs under normal AOMS latency. C2 (no top-level exception guard) will freeze the trigger guard permanently on any unhandled error in the pipeline. H1 (conviction_threshold unused) should be addressed concurrently as it silently voids a documented configuration contract. H2 (process leak) and H3 (race condition) are important for reliability under load. The rest are polishing items.

