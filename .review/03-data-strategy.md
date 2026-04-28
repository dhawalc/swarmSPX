# Code Review: Data Layer, Market Ingest, Strategy Selector
**Files**: db.py, market_data.py, schwab.py, tradier.py, options.py, selector.py, outcome_tracker.py
**Date**: 2026-04-27
**Verdict**: BLOCK — 3 CRITICAL bugs, 7 HIGH issues

---

## CRITICAL Issues

---

### [CRITICAL] DuckDB write-write deadlock under concurrent callers
**File**: `swarmspx/db.py:17-27`

**Issue**: DuckDB's default open mode is **read-write with a single writer lock**. The "short-lived connection" pattern here opens a new `duckdb.connect(path)` on every call, which works for reads but will **raise `duckdb.IOException: IO Error: Could not set lock on file`** when two connections from different threads/tasks try to write simultaneously. The scheduler fires a cycle at the same time the web route calls `store_snapshot()`, and `store_agent_votes()` loops N INSERT statements inside a single connection that is closed at the end — no `executemany`, no transaction, no explicit lock guard. Under CPython's GIL this may appear to work locally but will fail intermittently in production once the scheduler and FastAPI share a thread pool.

Additionally, `store_agent_votes` opens **one connection per vote loop** iteration — no, wait, it opens one connection and loops — but it does *not* wrap the loop in an explicit `BEGIN/COMMIT`. DuckDB auto-commits per statement in the default mode, so a crash mid-loop leaves partial vote rows.

**Fix**:
```python
# Option A: DuckDB connection pool with read_only=True for reads
# Option B: serialize via asyncio.Lock() for the file DB path
# Option C: promote to WAL mode (duckdb >= 0.10 supports read_write concurrent readers)

# Immediate fix for store_agent_votes:
conn.execute("BEGIN")
for vote in votes:
    conn.execute("INSERT INTO agent_vote_history ...", [...])
conn.execute("COMMIT")
```

---

### [CRITICAL] `_is_market_hours()` and `_get_session()` use server local time — timezone bomb
**File**: `swarmspx/ingest/market_data.py:225-227`, `swarmspx/strategy/selector.py:127-138`

**Issue**: Both use `datetime.now()` with **no timezone**. If the server is running in any timezone other than ET (US/Eastern), every session boundary is wrong. This is a deployed cloud service — the default timezone on most VPS / container environments is UTC.

- UTC vs ET is **5 hours** standard, **4 hours** during EDT.
- `_is_market_hours()` check `930 <= t <= 1600` will evaluate as `0930 UTC` to `1600 UTC`, meaning it believes market open at 9:30 AM UTC (4:30 AM ET) and close at 4:00 PM UTC (11:00 AM ET / noon EDT).
- `_get_session()` boundary `t < 1130` for "morning" will fire during pre-market in UTC, meaning **all pre-market signals are classified as "morning"** and eligible for afternoon lotto at the wrong time.
- Market session cut-off for "afternoon" at 1300 UTC = 8:00 AM ET — before the market even opens.

**Concrete bug**: on a UTC server, `_get_session()` returns `"afternoon"` from 9:00 AM UTC (5 AM ET) onward, so **every morning play is misrouted to lotto mode**.

**Fix**:
```python
import pytz
EASTERN = pytz.timezone("America/New_York")

def _get_session() -> str:
    now = datetime.now(tz=pytz.utc).astimezone(EASTERN)
    t = now.hour * 100 + now.minute
    ...
```
Same fix in `_is_market_hours()` and `OutcomeTracker._is_eod()`.

---

### [CRITICAL] Schema migration swallows errors silently — can corrupt live DB
**File**: `swarmspx/db.py:97-104`

**Issue**: The `try/except Exception` blocks that detect missing columns catch **all exceptions**, including `duckdb.TransactionException` (DB already in a failed transaction state), `duckdb.PermissionException`, `duckdb.OutOfMemoryException`, etc. If the `SELECT ... LIMIT 0` fails for any reason other than "column not found", the code runs `ALTER TABLE` unconditionally, which will fail with "column already exists" — but that error is also silently swallowed. The result: any DB corruption or transient IO error during startup silently converts to a no-op, and the application continues running with a broken schema.

Additionally, DuckDB's `ALTER TABLE ADD COLUMN` is **not idempotent** — running it twice raises an error (caught and swallowed here, which masks it).

**Fix**: Catch only the specific DuckDB `BinderException` (column not found), or use `INFORMATION_SCHEMA.COLUMNS`:
```python
cols = {row[0] for row in conn.execute(
    "SELECT column_name FROM information_schema.columns WHERE table_name = 'simulation_results'"
).fetchall()}
if "spx_entry_price" not in cols:
    conn.execute("ALTER TABLE simulation_results ADD COLUMN spx_entry_price DOUBLE DEFAULT 0.0")
```

---

## HIGH Issues

---

### [HIGH] Schwab 401 clears client but never re-authenticates — permanent failure loop
**File**: `swarmspx/ingest/schwab.py:62-64`

**Issue**: When a 401 is received, `self._client = None` is set. The next call to `_get_client()` calls `client_from_token_file()` again with the **same expired token** from disk. Since `schwab-py`'s `client_from_token_file` does not auto-refresh an expired token on its own (it needs a browser flow for initial auth; refresh tokens work silently only if the library handles it internally), the pattern is: 401 → clear → reload same expired token → 401 → infinite loop. Each failed call logs `Schwab client init failed` at ERROR level, but credentials (app_key, secret) are **not logged**, so at least that part is safe. The fix requires detecting whether the token file has been updated out-of-band by the schwab-py background refresh, or catching the 401 and waiting before retry.

**Fix**:
```python
if resp.status_code == 401:
    logger.warning("Schwab token may be expired; will retry on next cycle (no in-process refresh)")
    self._client = None
    return {}  # let caller fall back; do not tight-loop
```
Also add a `_last_auth_failure: Optional[datetime]` guard with a minimum 5-minute backoff before retrying token load.

---

### [HIGH] `enrich_with_options` is `async` but calls synchronous Schwab methods — mixed sync/async
**File**: `swarmspx/ingest/market_data.py:143-176`

**Issue**: `enrich_with_options` is declared `async def`, but the Schwab path calls `self.schwab.get_option_chain()` which is **fully synchronous** (uses `requests`-backed `schwab-py`). A blocking HTTP call inside an async function blocks the entire event loop for the duration of the request. With a 40-strike chain, `get_option_chain` can take 500ms–2s. The Tradier path is correctly awaited. The inconsistency means the web cycle blocks whenever Schwab options are fetched.

**Fix**: Run the Schwab call in a thread pool executor:
```python
loop = asyncio.get_event_loop()
raw_chain = await loop.run_in_executor(None, self.schwab.get_option_chain, "$SPX", 40)
```

---

### [HIGH] No rate limiting on Schwab — scheduler + web can burst 120 req/min limit
**File**: `swarmspx/ingest/market_data.py`, `swarmspx/ingest/schwab.py`

**Issue**: There is zero rate limiting. `get_snapshot()` calls `get_quotes` (1 req) + `get_futures` (1 req), and `enrich_with_options` calls `get_option_chain` (1 req = 3 req per cycle). If the scheduler fires every 30 seconds and the web dashboard polls on page load, you will sustain ~8–10 req/min normally. However, if multiple browser tabs are open plus scheduler concurrency, the burst ceiling is hit. Schwab's 120 req/min limit results in 429s, which are not currently handled (status != 200 logs a warning, returns empty dict, triggers yfinance fallback silently).

**Fix**: Add a simple token bucket or `asyncio.Semaphore` with a per-minute counter. At minimum, handle 429 responses explicitly and back off.

---

### [HIGH] `_calculate_vwap` is correct in yfinance path but Schwab path uses simple typical price
**File**: `swarmspx/ingest/market_data.py:67`, `swarmspx/ingest/market_data.py:206-211`

**Issue**: Two different computations are used under the same field name `spx_vwap`:

- **yfinance path** (line 206-211): Correct volume-weighted VWAP — `(typical_price * volume).cumsum() / volume.cumsum()`.
- **Schwab path** (line 67): `vwap = (high + low + price) / 3` — this is the **typical price** (TP), *not* VWAP. VWAP requires volume-weighting across intraday bars. The Schwab L1 quote only provides a single day's high/low/close with no per-bar volume.

The field `spx_vwap_distance_pct` is stored in the DB and used by agents to assess whether price is extended. For a strongly trending day, the typical-price approximation can differ from true VWAP by 0.3–0.8%, which is significant relative to SPX intraday moves of 0.5–1.5%.

**Impact quantification**: At SPX 5800, a 0.5% VWAP error = 29 points. `spx_vwap_distance_pct` can read "price is 0.4% above VWAP" when price is actually at VWAP, causing agents to think the market is extended when it is not.

**Fix**: Either label it `spx_typical_price_distance_pct` for honesty, or cache the day's OHLCV bar history from ES futures/Schwab candles to compute a real VWAP.

---

### [HIGH] `select_by_premium` evaluates `c.ask` for the "preferred cheapest" pick — wrong side for fills
**File**: `swarmspx/ingest/options.py:182`

**Issue**: `best = min(candidates, key=lambda c: c.ask)` selects the cheapest option by ask, which is correct for picking the most-OTM within the range. However, the calling code in `selector.py` also reads `trade["premium_ask"]` to present as the trade cost. For SPX options with wide spreads (typical bid/ask spread of $0.30–$1.00 for deep OTM), the fill will be somewhere between bid and ask. Using `ask` as cost overestimates what you'll pay if you work a limit order at mid. More importantly, `target_premium` is computed as `best.ask * 3` (line 184) — using the ask as entry basis further inflates the 3x target. If entry is at mid, the 3x target should be computed from mid, not ask.

**Fix**:
```python
result["target_premium"] = round(best.mid * 3, 2)  # 3x from mid price
result["entry_price_basis"] = best.mid  # what you'll likely pay
```

---

### [HIGH] `upsert_agent_score` has a TOCTOU race — read-then-write without a transaction
**File**: `swarmspx/db.py:310-332`

**Issue**: The SELECT-then-INSERT-or-UPDATE pattern on lines 315–331 is not wrapped in a transaction. Under concurrent access from two outcome resolution cycles (e.g., two signals resolve simultaneously), both callers can read "no existing row" and both attempt INSERT, causing a primary key collision. DuckDB will raise on the second INSERT. The `finally: self._close(conn)` will still close, but the second agent score update is silently lost (the exception propagates to `AgentScorer.process_signal_outcome` which may not catch it).

**Fix**:
```python
conn.execute("BEGIN")
existing = conn.execute("SELECT id FROM agent_scores WHERE agent_id = ? AND regime = ?", [...]).fetchone()
# ... UPDATE or INSERT ...
conn.execute("COMMIT")
```
Or use `INSERT OR REPLACE` / `ON CONFLICT DO UPDATE` if DuckDB supports it (it does as of 0.9+).

---

### [HIGH] OutcomeTracker resolution is pure SPX spot delta — completely wrong for options P&L
**File**: `swarmspx/tracking/outcome_tracker.py:80-96`

**Issue**: Win/loss is determined by `((current_spx - entry_spx) / entry_spx) * 100`. This measures the **underlying equity move**, not option P&L. For 0DTE options:

- A 0.3% SPX move ($17 on 5800) on a $7 call purchased with 0.30 delta = ~$5 gain = **+71% option P&L**.
- The tracker records `pnl_pct = +0.3%` — a "scratch" (below 0.05% threshold), when in reality the trade was a big winner.
- Conversely, theta decay of $7 over 2 hours on a no-movement day = `-100% option P&L`, but the tracker records `pnl_pct = 0.0%` — a scratch.

The `SCRATCH_THRESHOLD_PCT = 0.05` is calibrated for a stock % move, not an option premium move. For options, a 0.05% underlying move is noise; options P&L over 2 hours is dominated by gamma and theta.

**Consequence for Darwinian scoring**: ELO ratings are being updated based on whether SPX moved 0.05% in the signal's direction, not whether the actual trade made money. An agent that correctly calls a 0.5% SPX move would show "win" in ELO but the actual trade could be a loss if IV crushed on the move.

**Fix**: Either (a) store the option's mid premium at entry in `trade_setup` and compare to current option mid at resolution, or (b) use a larger underlying threshold (~0.2–0.3%) that corresponds to the breakeven move for 0DTE options at the typical premium ranges used.

---

## MEDIUM Issues

---

### [MEDIUM] `_is_choppy` logic contradiction — NEUTRAL with confidence > 55 triggers iron condor but selector also checks `direction == "NEUTRAL" and confidence < 55` for WAIT first
**File**: `swarmspx/strategy/selector.py:48-64`

**Issue**: The WAIT check at line 48 fires when `direction == "NEUTRAL" and confidence < 55`. The `_is_choppy` check fires when `direction == "NEUTRAL" and confidence > 55`. So a NEUTRAL signal with exactly 55 confidence hits neither condition. More importantly, the comment says "Consensus is 'stay put' — sell premium" for the neutral/high-confidence case, which is philosophically correct, but this path is only reached if `options_snapshot` is not None and not empty. The WAIT guard before line 44 only applies when there is *no* chain. So a NEUTRAL/high-confidence signal with a valid chain will correctly flow to iron condor — but this control flow is non-obvious and fragile.

**Fix**: Document the control flow explicitly or extract to a named function `_should_sell_premium()`.

---

### [MEDIUM] `_is_market_hours` in `market_data.py` uses arithmetic time comparison that fails at midnight rollover
**File**: `swarmspx/ingest/market_data.py:226`

**Issue**: `930 <= now.hour * 100 + now.minute <= 1600` — the arithmetic is correct for the intended range, but breaks for any `minute > 99` (impossible) and more relevantly: this compares *local* time against ET market hours (see timezone bug above). This is a secondary symptom of the timezone bug but worth noting separately.

---

### [MEDIUM] `enrich_with_options` is `async` but `get_snapshot()` is sync — caller must be careful
**File**: `swarmspx/ingest/market_data.py:33,143`

**Issue**: `get_snapshot()` is sync, `enrich_with_options()` is async. Callers that call `get_snapshot()` and then `await enrich_with_options()` in the same function are mixing sync and async data fetching. The web cycle likely calls both. If the caller is a sync function, `enrich_with_options` can never be awaited, so options enrichment is silently skipped. The test `test_market_data_graceful_without_tradier` and related tests are all `async`, suggesting the intended caller is async — but `get_snapshot` is sync. This design is inconsistent.

---

### [MEDIUM] Iron condor `max_risk` computation is asymmetric — uses `max(call_width, put_width)` not per-side
**File**: `swarmspx/ingest/options.py:307`

**Issue**: `max_risk = round(max(call_width, put_width) - net_credit, 2)` takes the wider wing and subtracts total net credit. This is only correct if both wings are exactly equal width. For an asymmetric condor (wider put wing, say 25 vs 20 for calls), the actual max risk on each side is different:
- Call side max loss: `call_width - net_credit` (if market rips through call short)  
- Put side max loss: `put_width - net_credit` (if market crashes through put short)  

Using `max(...)` overstates risk for the narrower wing, which causes `rr_ratio` to be understated, making the trade look less attractive than it is.

---

### [MEDIUM] `store_agent_votes` opens one connection per signal but loops votes inside — autocommit means partial writes on exception
**File**: `swarmspx/db.py:247-267`

Already covered under the CRITICAL transaction issue, but also note: if a single `conn.execute(INSERT)` fails mid-loop (e.g., sequence overflow, constraint violation), the connection is closed in `finally` with no rollback, leaving 0..N-1 votes committed and the last vote missing. DuckDB does not auto-rollback on close.

---

### [MEDIUM] `get_agent_scores` parameter typed as `str` but defaults to `None` — mypy error
**File**: `swarmspx/db.py:286`

Already flagged by mypy: `def get_agent_scores(self, regime: str = None)` — missing `Optional[str]`. This will raise `TypeError` if `mypy --strict` is enforced downstream.

**Fix**: `def get_agent_scores(self, regime: Optional[str] = None)`

---

### [MEDIUM] Unused variables and imports (ruff findings)
**Files**: multiple

- `swarmspx/ingest/market_data.py:101` — `import pandas as pd` imported but never used (F401)
- `swarmspx/ingest/schwab.py:11` — `datetime` and `timezone` imported but unused (F401)
- `swarmspx/ingest/schwab.py:13` — `Optional` imported but unused (F401)
- `swarmspx/ingest/options.py:207` — `option_type` assigned but never used (F841)
- `swarmspx/tracking/outcome_tracker.py:6` — `timedelta` imported but unused (F401)

---

## CORRECT / WELL-IMPLEMENTED

The following were reviewed and are correct:

- **Delta sign convention**: `select_strikes` correctly filters `c.delta < 0` for puts and `c.delta > 0` for calls. Schwab normalizer sets put delta to the signed value from the API. Tradier stores negative deltas for puts in `SAMPLE_CHAIN_RESPONSE`. Both correct.
- **`select_by_premium` walk direction**: calls filter `c.strike > spx_price`, puts filter `c.strike < spx_price` — correct OTM direction for both sides.
- **Vertical spread R:R formula**: `max_gain = width - net_debit`, `rr_ratio = max_gain / net_debit` — correct.
- **`_calculate_vwap` in yfinance path**: volume-weighted cumulative method is a correct intraday VWAP implementation.
- **Tradier response shape handling**: `OptionContract.from_raw()` delegates to `from_tradier()`, and `_normalize_option()` in schwab.py converts Schwab's schema to match the same Tradier-compatible shape. Both sources produce identical field names. The `OptionContract.from_tradier()` handles both correctly.
- **PCR calculation**: `total_put_vol / total_call_vol` with guard for zero — correct.
- **ATM IV normalization**: `round(atm_iv * 100, 1) if atm_iv < 1 else round(atm_iv, 1)` correctly detects whether IV is in decimal form (Schwab: `volatility/100`) vs already-percent form.
- **Iron condor leg construction**: short strikes at ~0.16 delta, long wings further out — correct structure, correct credit/debit calculation.
- **Regime thresholds**: VIX 15/20/25 boundaries are standard; `low_vol_grind` vs `low_vol_trending` split at 0.5% change is reasonable.
- **Schwab `_normalize_option`**: divides `volatility` by 100 (Schwab returns IV as percentage) — correct.
- **Tradier `get_options_chain` default to today for 0DTE**: correct behavior.
- **Test coverage**: `test_strategy.py` and `test_tradier.py` are well-structured, cover happy path + edge cases, mock session correctly with `@patch`.

---

## Test Gaps

1. No test for timezone-aware session classification.
2. No test for `_is_market_hours()` with a UTC server.
3. No test for `OutcomeTracker` that verifies win/loss classification matches option P&L (not just underlying move).
4. No test for `upsert_agent_score` concurrent race.
5. No test for `init_schema` idempotency / migration correctness on a pre-existing DB.
6. No test for Schwab 401 handling (retry loop / backoff).
