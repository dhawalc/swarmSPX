# Code Review — SwarmSPX Surfaces (Web, Alerts, Scheduler, Briefing, CLI)
**Reviewer:** Claude Sonnet 4.6  
**Date:** 2026-04-27  
**Files:** web/app.py · web/routes.py · web/state.py · web/ws_manager.py · alerts/dispatcher.py · alerts/telegram.py · alerts/slack.py · scheduler.py · briefing.py · cli.py

---

## CRITICAL Issues

---

### [CRITICAL] Race condition on `POST /api/cycle/trigger`
**File:** `swarmspx/web/routes.py:76-81`

**Issue:** The guard reads state and then fires `asyncio.ensure_future()`. Both checks happen synchronously in the same coroutine *before* the event loop runs the cycle. Two near-simultaneous HTTP requests will both read `status == "idle"`, both pass the guard, and both schedule `engine.run_cycle()`. The cycle state is not updated synchronously at trigger time — it only transitions to `"running"` later, when `CycleState._on_cycle_started` receives an event emitted by the engine. There is no lock, no flag set on trigger, and no deduplication.

**Fix:**
```python
# In CycleState, add a flag set atomically at trigger:
def try_start(self) -> bool:
    """Return True if a cycle was not already claimed; sets status to 'queued'."""
    if self._state["status"] in ("running", "deliberating", "queued"):
        return False
    self._state["status"] = "queued"   # synchronous, no await needed
    return True

# In trigger_cycle():
if not state.try_start():
    raise HTTPException(status_code=409, detail="Cycle already in progress")
asyncio.ensure_future(engine.run_cycle())
```
`try_start` runs synchronously in the same event loop turn — no second coroutine can race past it before the function returns because the event loop is cooperative.

---

### [CRITICAL] Backtest endpoint blocks the event loop
**File:** `swarmspx/web/routes.py:112-181`

**Issue:** `/api/backtest` runs a tight Python `for i in range(signals)` loop — up to 10,000 iterations — directly in an `async def` route handler, with no `await` inside the loop. Because CPython's asyncio event loop is single-threaded, this loop yields no control back to the event loop for the entire duration. All WebSocket broadcasts, in-flight cycle events, and other HTTP requests are frozen while a 10k backtest runs. On a benchmarked machine, 10k iterations with `AgentScorer.process_signal_outcome` (which performs DuckDB writes) can take 2–15 seconds depending on disk I/O.

**Fix:** Offload to a thread executor so the event loop remains responsive:
```python
import asyncio
loop = asyncio.get_event_loop()

def _run_backtest_sync(signals, seed):
    # ... all the for-loop logic here ...
    return wins, losses, leaderboard

wins, losses, leaderboard = await loop.run_in_executor(
    None, _run_backtest_sync, signals, seed
)
```
Alternatively, add chunked `await asyncio.sleep(0)` every N iterations as a lighter-weight option.

---

### [CRITICAL] No authentication on any endpoint — server defaults to 0.0.0.0
**File:** `swarmspx/cli.py:29`, `swarmspx/web/routes.py`

**Issue:** `--host` defaults to `0.0.0.0`, exposing the dashboard on all network interfaces. There is no authentication middleware anywhere in the FastAPI app. Any host on the same LAN (or internet if port-forwarded) can:
- Hit `POST /api/cycle/trigger` to spam cycles
- Call `POST /agents/custom` to inject arbitrary agent payloads
- Call `DELETE /agents/custom/{id}` to remove agents
- Read all trade signals and leaderboard data

The `/api/backtest` endpoint with no auth also creates a trivial DoS vector.

**Fix (minimum viable):**
```python
import secrets
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

bearer = HTTPBearer()
API_TOKEN = os.environ["SWARMSPX_API_TOKEN"]  # fail fast if not set

async def verify_token(creds: HTTPAuthorizationCredentials = Security(bearer)):
    if not secrets.compare_digest(creds.credentials, API_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid token")

router = APIRouter(prefix="/api", dependencies=[Depends(verify_token)])
```
At minimum, bind to `127.0.0.1` by default and only expose to LAN intentionally.

---

### [CRITICAL] WebSocket broadcast stalls on slow/stuck clients
**File:** `swarmspx/web/ws_manager.py:78-87`

**Issue:** `_broadcast` iterates `self._connections` sequentially and `await`s each `ws.send_text()` one at a time. A single client with a slow TCP buffer or a stalled connection will hold up delivery to all other clients. If the stuck client never closes the connection (just stops reading), `send_text` will block indefinitely — or until the OS TCP timeout (minutes), not the WebSocket timeout. FastAPI/Starlette's `send_text` has no per-client timeout.

Additionally, `self._connections` is a plain `list[WebSocket]`. `connect()` appends to it and `disconnect()` calls `list.remove()`. These are not atomic — if `_broadcast` is iterating the list and `connect()` appends concurrently (two coroutines can interleave at an `await`), the iteration sees a mutating list. In practice Python list iteration over a growing list is safe (it won't crash), but a newly appended WS could be skipped or included mid-loop depending on timing.

**Fix:**
```python
# Use asyncio.wait_for for per-client timeout, and gather for parallel sends:
async def _broadcast(self, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, default=str)
    dead: list[WebSocket] = []
    # Snapshot the list before iteration
    connections = list(self._connections)
    results = await asyncio.gather(
        *[asyncio.wait_for(ws.send_text(raw), timeout=5.0) for ws in connections],
        return_exceptions=True,
    )
    for ws, result in zip(connections, results):
        if isinstance(result, Exception):
            dead.append(ws)
    for ws in dead:
        self.disconnect(ws)
```

---

## HIGH Issues

---

### [HIGH] Dead connection cleanup missing on `connect()` failure
**File:** `swarmspx/web/ws_manager.py:54-60`

**Issue:** `connect()` appends to `_connections` *before* sending the hydration snapshot. If `_send()` raises (e.g., the client disconnects immediately after handshake), the WS is in `_connections` forever — `disconnect()` is never called because the exception is swallowed in `_send` with a bare `except: pass`. The WebSocket endpoint in `app.py` only calls `mgr.disconnect(ws)` on `WebSocketDisconnect`, which won't fire if the connection was never fully established.

```python
# _send silently swallows ALL exceptions:
async def _send(ws, payload):
    try:
        await ws.send_text(...)
    except Exception:
        pass   # leaked connection
```

**Fix:** Add the WS to connections only after successful initial send, or catch the exception in `connect()` and remove it:
```python
async def connect(self, ws: WebSocket) -> None:
    await ws.accept()
    self._connections.append(ws)
    try:
        snapshot = self._state.get_snapshot()
        await ws.send_text(json.dumps({"type": "full_state", "data": snapshot}, default=str))
    except Exception:
        self.disconnect(ws)
        return
    log.info("WebSocket client connected (%d total)", len(self._connections))
```

---

### [HIGH] Scheduler timezone arithmetic produces invalid hours
**File:** `swarmspx/scheduler.py:70`

```python
current_h = now.hour + self.tz_offset
```

**Issue:** `now.hour` is from the server's local clock. If the server is in UTC (common on Linux cloud instances) and `tz_offset=0` (the default, meaning "server IS ET"), the comparison `current_h == 8` at 8:00 AM server-time will trigger — but 8:00 AM UTC is 3:00 AM ET. No schedule slot will ever fire on a UTC server with default settings unless the user passes `--tz-offset -5` or `-4` (DST). The parameter name "hours offset from ET" is backwards: if server is UTC and ET is UTC-5, you need to *subtract* 5 from server hours, not add. The current code adds. If someone passes `tz_offset=5` thinking "I'm 5 hours from ET" they get `current_h` values up to 28.

Additionally, `current_h` is never clamped to 0-23. A value of 25 will never match any schedule entry, silently missing all slots.

**Fix:** Use timezone-aware datetime throughout:
```python
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")

now_et = datetime.now(ET)
current_h = now_et.hour
current_m = now_et.minute
```
Remove `tz_offset` entirely or keep it only for environments without `zoneinfo`.

---

### [HIGH] Midnight reset race: `_ran_today.clear()` at minute 0:00 blocks if cycle runs late
**File:** `swarmspx/scheduler.py:73-75`

**Issue:** The midnight reset `if current_h == 0 and current_m == 0: self._ran_today.clear()` fires during the same 30-second polling window when the check loop runs. If the scheduler's `asyncio.sleep(30)` woke up at 23:59:45, the clear runs at approximately 00:00:15. But if a scheduled slot (e.g. 15:45) ran long and the sleep call was delayed, the reset could be missed for the entire 00:00 minute window, meaning `_ran_today` is never cleared and *no slots fire the next day*. This is a hard silent failure.

**Fix:** Track the date explicitly:
```python
_last_reset_date: date | None = None

if now_et.date() != self._last_reset_date:
    self._ran_today.clear()
    self._last_reset_date = now_et.date()
```

---

### [HIGH] Daily summary silently misses signals when more than 10 fired today
**File:** `swarmspx/scheduler.py:124-126`

```python
signals = self._engine.db.get_recent_signals(limit=10)
today_signals = [s for s in signals if ...]
```

**Issue:** `get_recent_signals(limit=10)` fetches the 10 most recent signals *ever* — not today's. On a normal trading day with 5 scheduled cycles plus any manually triggered ones, there will be exactly 4-5 today. But if prior days' signals happen to be the most recent 10, today's signals could be entirely excluded. More critically, if the DB has 11 signals today, signal #1 is silently dropped from the summary P&L calculation. The `limit=10` is an arbitrary cap with no comment explaining why.

**Fix:** Pass today's date as a filter to `get_recent_signals`, or use `limit=100` (same-day signals will never realistically exceed that):
```python
signals = self._engine.db.get_recent_signals(limit=100)
```
Or add a `since: datetime` parameter to the DB method.

---

### [HIGH] Telegram MarkdownV2 escape does not cover `\` (backslash)
**File:** `swarmspx/alerts/telegram.py:17-25`

**Issue:** The Telegram MarkdownV2 spec requires escaping `\` (backslash) itself. The current `special` string is:
```python
special = r"_*[]()~`>#+-=|{}.!"
```
`\` is absent. If any field value contains a backslash (e.g., a filesystem path, a regex pattern in a rationale string, or a Windows-style price string), the message will fail with a Telegram parse error (400 Bad Request), the exception is logged as `Telegram send failed: ...` and the alert is silently dropped.

**Fix:**
```python
special = r"\\_*[]()~`>#+-=|{}.!"
# Or equivalently, escape backslash first before processing other chars:
def _escape_md2(text: str) -> str:
    special = r'\_*[]()~`>#+-=|{}.!'
    out = []
    for ch in str(text):
        if ch == '\\' or ch in special:
            out.append(f'\\{ch}')
        else:
            out.append(ch)
    return ''.join(out)
```
Backslash must be escaped *first* to avoid double-escaping other characters.

---

### [HIGH] Slack Block Kit: `blocks` nested inside `attachments` is deprecated/broken schema
**File:** `swarmspx/alerts/slack.py:137-144`

**Issue:** The payload structure wraps Block Kit blocks inside a legacy `attachments` array:
```python
return {"attachments": [{"color": "...", "blocks": blocks}]}
```
Slack's current Block Kit spec does not support `blocks` as a key inside `attachments`. Blocks inside attachments are a legacy fallback that Slack still partially renders, but `header` block type is not supported inside attachments — it is a top-level message block only. The `header` blocks in `format_trade_card`, `format_outcome`, and `format_error` will either be silently dropped or cause a Slack API error.

The correct structure for colored side-bar + blocks is to use `attachments[].blocks` only with `section`/`divider`/`context` types (not `header`), or use a top-level `blocks` array for the header plus `attachments` only for the color sidebar:
```python
return {
    "blocks": [header_block],
    "attachments": [{"color": color, "blocks": body_blocks}]
}
```

---

### [HIGH] Alert dispatcher: exceptions in `_handle` crash the listener loop
**File:** `swarmspx/alerts/dispatcher.py:73-80`

**Issue:** `_listen` wraps the loop in a `try/except asyncio.CancelledError` only. If `_handle` raises any other exception (e.g., `format_trade_card` throws a `KeyError` on an unexpected card shape, or `send_telegram` raises something not caught), the exception propagates out of `_listen`, the task is marked done, and **all future alerts are silently dropped for the rest of the process lifetime**. There is no restart logic, no error logging at the loop level.

```python
async def _listen(self) -> None:
    try:
        while True:
            event = await self._queue.get()
            await self._handle(event)   # unguarded
    except asyncio.CancelledError:
        return
    # any other exception exits here — loop is dead
```

Note: `_on_trade_card`, `_on_outcome`, `_on_error` do use `asyncio.gather(return_exceptions=True)` for the send calls, so network errors won't crash the loop. But formatting exceptions in `format_trade_card`/`format_outcome` run *before* `gather` and are unprotected.

**Fix:**
```python
async def _listen(self) -> None:
    while True:
        try:
            event = await self._queue.get()
            await self._handle(event)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.error("AlertDispatcher._handle raised: %s", exc, exc_info=True)
            # loop continues
```

---

### [HIGH] Briefing failure handling: Schwab down → silent degraded send with zero values
**File:** `swarmspx/briefing.py:41-73`

**Issue:** `_gather_data` calls `self.schwab.get_spx_vix()` and `get_futures()` behind `if self.schwab.is_configured` guards, silently defaulting to empty dicts. If Schwab is configured but the API call fails (network error, auth expiry), those methods may return empty dicts, None, or raise. The outer `try/except` on the options chain logs a warning, but the SPX/VIX/ES calls have no exception handler — any exception propagates up through `run()` to the scheduler's `except Exception as e`, which logs and sends a Telegram error. That's actually the correct flow, but the user sees a cryptic `Scheduled run 8:00 failed: ...` rather than a useful degraded briefing.

Separately: when `is_configured` is False, the briefing sends zeroed-out values (`SPX prev close: $0.00`, `VIX: 0.0`) to Telegram, which reads as a real signal. It should clearly label itself as unavailable.

**Fix:** Return a `status: degraded` field and include it prominently in the Telegram message when data sources are unavailable.

---

## MEDIUM Issues

---

### [MEDIUM] Duplicate dead-connection logic in `_on_trade_card` — unreachable second check
**File:** `swarmspx/alerts/dispatcher.py:95-105`

```python
if confidence < self.min_confidence:
    ...
    return

has_special = bool(card.get("contrarian_alert") or card.get("herding_warning"))
if confidence < self.min_confidence and not has_special:
    return
```

The second `if confidence < self.min_confidence` check at line 105 is unreachable — if confidence is below the threshold, the first block already returned. The intent appears to be: "send if confidence >= threshold OR has special alert". The first `return` breaks this logic entirely. High-confidence cards with no special alert are handled correctly, but a low-confidence card with a contrarian alert will be caught by the first `return` before `has_special` is ever evaluated.

**Fix:**
```python
has_special = bool(card.get("contrarian_alert") or card.get("herding_warning"))
if confidence < self.min_confidence and not has_special:
    logger.debug(...)
    return
```

---

### [MEDIUM] `routes.py` engine captured at router creation time, not request time
**File:** `swarmspx/web/routes.py:21`, `swarmspx/web/app.py:100`

```python
app.include_router(create_router(state, engine))  # engine may be None here
```

`create_router` is called in `create_app()` before the lifespan runs. At that point `engine` is the value passed to `create_app()` — which could be `None` if no engine was injected. The lifespan later does `engine = SwarmSPXEngine(...)` and sets `app.state.engine`, but the `engine` reference captured in the router closure still points to the original `None`. The lazily-created engine is stored on `app.state.engine` but the router uses its own closure variable. This means all endpoints that call `engine.db`, `engine.forge`, etc., would `AttributeError: 'NoneType' object has no attribute 'db'` at runtime when the web server is started without an injected engine (the default case from `cli.py`).

Verify this: `_run_web` in `cli.py` always injects an engine, so this is currently masked. But it's a latent bug for any caller using `create_app()` with `engine=None`.

**Fix:** Have route handlers read `request.app.state.engine` (like the leaderboard and profile endpoints already do correctly) rather than relying on the closure variable.

---

### [MEDIUM] `routes.py` — missing type annotation on `body: dict`
**File:** `swarmspx/web/routes.py:57`

`async def add_custom_agent(body: dict) -> dict:` uses a bare `dict` as the request body type. FastAPI requires a Pydantic model for proper validation, documentation, and error messaging. A bare `dict` bypasses input validation entirely — any JSON will be accepted and forwarded to `engine.forge.add_custom_agent()`.

---

### [MEDIUM] Bare `except Exception` swallows structured errors in `_send_daily_summary`
**File:** `swarmspx/scheduler.py:129`

`datetime.fromisoformat(str(s["timestamp"]))` will raise `ValueError` for any malformed timestamp from the DB. This propagates through `_send_daily_summary` up to `_run_cycle`, which has no inner guard, then up to the scheduler's outer `except Exception as e`. A single bad DB row will prevent the daily summary from sending with no granular logging.

---

### [MEDIUM] `app.py` — `asyncio` imported but unused; E402 import order violation
**File:** `swarmspx/web/app.py:12, 22-30`

`import asyncio` is unused (ruff F401). `load_dotenv()` call at line 23 causes all subsequent swarmspx imports to be flagged as E402 (module-level import not at top of file). Move `load_dotenv()` call into the `lifespan` function or into `__init__` of a settings module, keeping all imports at the top.

---

### [MEDIUM] `scheduler.py` — imported `time as dtime` and `Optional` are unused
**File:** `swarmspx/scheduler.py:17-18`

`from datetime import datetime, time as dtime` — `dtime` never used. `from typing import Optional` — never used. Same pattern in `briefing.py` (`SchwabClient`, `OptionsSnapshot`, `Optional` all unused).

---

### [MEDIUM] `scheduler.py` — `print()` used instead of logging in CLI output
**File:** `swarmspx/cli.py:116-118`

Three bare `print()` calls in `_run_schedule`. Should use `logger.info()` for consistency with the rest of the codebase.

---

### [MEDIUM] CORS not configured
**File:** `swarmspx/web/app.py`

No `CORSMiddleware` is added to the FastAPI app. For a dashboard accessed from a browser at `http://localhost:8420` this is fine (same-origin). If the dashboard is ever embedded or accessed from a different port/domain (e.g., a Cloudflare tunnel), all fetch/WebSocket requests will be blocked by CORS preflight. Recommend adding explicit CORS config with a restrictive origin list rather than discovering this at deployment.

---

### [MEDIUM] Static file path traversal: mitigated by Starlette but undocumented
**File:** `swarmspx/web/app.py:115, 118-119`

```python
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
...
return FileResponse(STATIC_DIR / "index.html")
```

`StaticFiles` is safe against path traversal by default (Starlette normalises paths). The `FileResponse(STATIC_DIR / "index.html")` is a hardcoded path, not user-controlled, so it's safe. No action required, but worth documenting.

---

## Summary Table

| ID | Severity | File | Issue |
|----|----------|------|-------|
| 1 | CRITICAL | routes.py:76-81 | Race condition on cycle trigger — no atomic guard |
| 2 | CRITICAL | routes.py:112-181 | Backtest blocks event loop up to 15s at 10k signals |
| 3 | CRITICAL | cli.py:29, routes.py | No auth on any endpoint; 0.0.0.0 default binding |
| 4 | CRITICAL | ws_manager.py:78-87 | Sequential broadcast stalls all clients on one slow socket |
| 5 | HIGH | ws_manager.py:54-60 | Leaked WS connection if initial send fails |
| 6 | HIGH | scheduler.py:70 | TZ arithmetic produces invalid hours; UTC servers fire nothing |
| 7 | HIGH | scheduler.py:73-75 | Midnight reset can be missed; next day's slots never fire |
| 8 | HIGH | scheduler.py:124-126 | Daily summary misses signals when >10 today |
| 9 | HIGH | telegram.py:18 | MD2 escape missing `\`; backslash in any field drops alert silently |
| 10 | HIGH | slack.py:137-144 | `header` blocks inside `attachments` unsupported; messages broken |
| 11 | HIGH | dispatcher.py:73-80 | Unhandled exception in `_handle` kills listener loop permanently |
| 12 | HIGH | briefing.py:41-73 | Unconfigured Schwab sends zero-valued briefing without warning |
| 13 | MEDIUM | dispatcher.py:95-105 | Unreachable code — first guard kills special-alert bypass logic |
| 14 | MEDIUM | routes.py:21 + app.py:100 | Closed-over `engine=None` latent bug when no engine injected |
| 15 | MEDIUM | routes.py:57 | `body: dict` bypasses FastAPI/Pydantic validation |
| 16 | MEDIUM | scheduler.py:129 | Malformed DB timestamp crashes daily summary silently |
| 17 | MEDIUM | app.py:12,22-30 | Unused import + E402 import order violations (ruff: 26 issues) |
| 18 | MEDIUM | scheduler.py:17-18, briefing.py | Multiple unused imports across files |
| 19 | MEDIUM | cli.py:116-118 | `print()` instead of `logging` in schedule runner |
| 20 | MEDIUM | app.py | No CORS middleware configured |

---

**Verdict: BLOCK — 4 CRITICAL, 8 HIGH issues.**

Priority fix order: auth (#3), event loop blocking (#2), race condition (#1), WS broadcast (#4), scheduler timezone (#6) + midnight reset (#7), alert loop crash (#11), Slack schema (#10), MD2 backslash (#9).
