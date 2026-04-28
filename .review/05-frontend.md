# SwarmSPX Frontend Review — 05-frontend.md
**Date:** 2026-04-27  
**Files:** swarm.js, agent_network.js, components.js, leaderboard.js, index.html  
**Uncommitted diff:** agent_network.js (+10 lines ELO badge), leaderboard.js (new file, 264 lines)

---

## Summary

The codebase is a well-structured vanilla-JS frontend with an IIFE pattern for `AgentNetwork`
and `Leaderboard`, a single global `SwarmState`, and a DOM CustomEvent bus. For a trading
dashboard this is appropriate — no framework needed. There is no XSS exposure on
server-controlled fields, `_escHtml`/`_esc` are used consistently in every innerHTML write.
The render loop has a good idle-throttle strategy. However, there are several HIGH issues
relating to per-frame GPU cost, a confirmed agent_id mismatch that silently breaks leaderboard
row colors, an untracked `eloColor` NaN path in the new ELO badge, and no touch support on
the canvas visualization.

---

## CRITICAL

None found.

---

## HIGH

### H1 — Agent ID mismatch: `putcall_pete` vs `put_call_pete` — leaderboard colors/names silently broken

**Files involved:**
- `agent_network.js` line 22: `agents: [..., "putcall_pete", ...]` (no underscore between put and call)
- `agent_network.js` line 60: `AGENT_META` key is `putcall_pete`
- `leaderboard.js` lines 29, 44: `AGENT_TRIBE` and `AGENT_NAMES` keys are `put_call_pete` (with underscore)
- `scoring.py` line 69: backend `KNOWN_AGENTS` uses `put_call_pete` (the canonical form)
- `backtest/engine.py` line 16: uses `putcall_pete` — the backend is also inconsistent

The leaderboard API returns `agent_id = "put_call_pete"`. When `leaderboard:updated` fires,
`_eloMap["put_call_pete"]` is populated. `AgentNetwork._applyEloToNodes()` iterates `nodes`,
whose id is `"putcall_pete"`. The lookup `_eloMap[n.id]` misses — that node's `eloRadius`
is stuck at 24, `eloTintColor` is null, and `n.elo` is undefined.

In `_showHoverCard`, `n.elo` resolves via `n.elo || _eloMap[n.id]`. Both are undefined.
`eloColor` is computed as `elo >= 1050 ? ... : elo <= 950 ? ... : "var(--text-dim)"`. When
`elo` is `undefined`, both comparisons are `false`, so it falls through to `"var(--text-dim)"`.
This is not catastrophic but is silent data loss: that agent always shows default ELO in the
network and in the hover card.

`leaderboard.js` `AGENT_TRIBE["putcall_pete"]` is also undefined, so `tribe` falls back to
`"technical"` at line 186 — wrong tribe color for that leaderboard row.

**Fix:** Standardise on `put_call_pete` everywhere. The canonical source is `scoring.py`.
Update `agent_network.js` TRIBES agents array (line 22), AGENT_META key (line 60), and
`backtest/engine.py` (line 16).

---

### H2 — Per-frame `shadowBlur` applied 13+ times inside `_drawNode` — GPU stall risk

`agent_network.js` sets `ctx.shadowBlur` to non-zero values at 13 call sites, all inside
`_draw()` which runs every frame. Canvas `shadowBlur` forces a GPU composite pass per shape;
browsers do not batch these. With 24 nodes each potentially triggering conviction halo,
vote-glow, flip-flash, dashed ring, inner ring, and conviction arc paths — all with
`shadowBlur` set — you can easily reach 60-120 shadow operations per frame at 60 fps.

The existing `dotGridCanvas` cache pattern shows the author understands caching; the same
technique should be applied here. An offscreen node texture (or grouping all shadow ops into
a single `ctx.save()`/`ctx.restore()` block with shadowBlur set once) would cut compositing
cost significantly on low-end GPUs.

**Specific locations:**
- `_drawNode`: lines 794, 796 (halo glow), 813 (vote glow), 827 (flip flash), 879 (main circle)
- `_drawConnections`: lines 630-636 (per-pair shadow inside O(n²) loop)
- `_drawDataParticles`: line 708 (per-particle ctx.save with shadowBlur=6)
- `_drawShockwaves`: no shadowBlur (good, uses gradient instead — this is the right pattern)

The intra-tribe connection loop at lines 610-658 is O(n²) per tribe (15 pairs × 4 tribes =
60 draw calls per frame) with `shadowBlur` set on every agreeing pair. During consensus glow
it adds a full O(n²) across all nodes (276 pairs). This is the highest single-frame cost path.

---

### H3 — `_eloMap` defined in `AgentNetwork` scope but never accessible by `Leaderboard`; wiring is correct but fragile

The 5-line uncommitted diff adds ELO badge rendering using `n.elo || _eloMap[n.id]` at line
1047 of `agent_network.js`. The `_eloMap` module-level variable (line 95) is populated via the
`leaderboard:updated` CustomEvent. This wiring is correct and functional.

However there is a subtle NaN bug in the new code:

```js
const eloColor = elo >= 1050 ? "var(--bull)" : elo <= 950 ? "var(--bear)" : "var(--text-dim)";
```

When `elo` is `undefined` (before first leaderboard fetch, or for the mismatched `putcall_pete`
agent), both comparisons evaluate to `false`, giving `"var(--text-dim)"`. This is benign.

But `eloStr` is: `` ` &bull; ELO ${Math.round(elo)}` `` — `Math.round(undefined)` returns
`NaN`, rendering as the literal text `"• ELO NaN"` in the hover card until leaderboard loads.
The guard `elo ? ...` in the template expression prevents this only if `elo` is falsy. Since
`elo` could be `0` (theoretically), the guard `elo ?` would suppress a legitimate zero-ELO
display. More importantly: if `n.elo` is set from a previous leaderboard fetch (a number) but
`_eloMap[n.id]` has not yet been populated (race on first load), `n.elo || _eloMap[n.id]`
will correctly resolve. The actual NaN issue occurs only before any fetch completes.

**Fix:** Guard with `elo != null` rather than truthy: `elo != null ? ... : ""`.

---

### H4 — WebSocket duplicate handler risk on reconnect

`WS._open()` creates a new `WebSocket` and assigns fresh `.onopen`, `.onclose`, `.onmessage`
handlers. The guard `if (this.socket && this.socket.readyState <= 1) return` prevents opening
a second socket while one is `CONNECTING(0)` or `OPEN(1)`. However the `onmessage` handler
calls `_dispatch()` which adds to `document`-level listeners registered in `_listen()` —
those are added once in `AgentNetwork.init()` and `components.js` DOMContentLoaded. They are
never removed. If the page stays open for hours and reconnects many times, no handler
accumulates (they are property assignments, not `addEventListener`). This is safe.

The one actual risk: `_retry()` uses `Math.pow(1.5, retryCount)` with no cap on `retryCount`.
After ~24 reconnects, the computed delay is already at `maxRetry (30,000ms)` due to the
`Math.min` clamp. `retryCount` then grows unboundedly as a 53-bit float integer. Not a
meaningful leak, but `retryCount` could be clamped after it hits the maxRetry plateau to keep
the number tidy. Low priority.

No handlers are duplicated on reconnect. **This specific concern is not a real bug** but
noted for clarity.

---

## MEDIUM

### M1 — `thoughtBubbles` text is rendered raw from `node.reasoning` into Canvas — not into innerHTML

`_drawThoughtBubbles()` renders `tb.text` via `ctx.fillText()` — Canvas API. This is not XSS.
No escaping needed here. Confirmed safe.

The `n.reasoning` → `_escHtml()` path in `_showHoverCard()` (line 1061) is correctly escaped.
No XSS exposure found anywhere in the codebase. `_esc` and `_escHtml` are used at every
`innerHTML` call site. One mild concern: `leaderboard.js` `_renderRows()` line 193 builds
`tip` as a `title=""` attribute value:
```js
const tip = _esc(name) + " · ELO " + row.elo + " · " + row.wins + "W/" + row.losses + "L";
```
`_esc(name)` HTML-escapes content via `div.innerHTML`, but the result is then placed inside
a double-quoted HTML attribute. Characters like `"` inside an agent name would break the
attribute boundary. Since `AGENT_NAMES` is a static hardcoded map, this can never actually
trigger. But if `row.agent_id` is used as fallback for `name` (e.g., an unexpected agent_id
from the API), a crafted `agent_id` could inject into `title`. Low risk given the backend
validates against `KNOWN_AGENTS`.

---

### M2 — No touch support on canvas — mobile UX is completely broken for the network panel

`_initHoverCard()` registers `mousemove` and `mouseleave` only. On touch devices, hovering an
agent node is impossible; the hover card never shows, and there is no touch-equivalent
interaction. `MobileTabs` switches panels but the network canvas has zero touch interactivity.
For a long-running dashboard this is a notable UX gap.

---

### M3 — `_buildDotGridCache()` called on every resize, leaks previous offscreen canvas

`_resize()` calls `_buildDotGridCache()` which creates `dotGridCanvas = document.createElement("canvas")`.
The previous `dotGridCanvas` is simply overwritten with no explicit disposal. Browsers GC
detached canvases but the `CanvasRenderingContext2D` held by `dotGridCanvas.getContext("2d")`
may hold GPU texture memory until GC collects. On frequent resize events (e.g., DevTools
panel drag) this creates transient GPU memory pressure. A fix is `dotGridCanvas = null` before
creating the replacement (already overwritten, so this is cosmetic), or throttling resize
via `debounce`.

---

### M4 — `ConsensusGauge._animateArc` uses floating `requestAnimationFrame` — no cancel handle

`_animateArc` spawns a rAF loop via internal `step()`. If `render()` is called again while
the animation is running, `_animating = true` blocks a second `_animateArc` call, so only one
loop runs. However `_animTarget` is updated immediately, and the running loop will converge to
the new target. This is correct. The loop terminates naturally (no cancel needed for finite
convergence). Non-issue functionally, but the rAF handle is not stored, so there is no way to
cancel it during `_reset()`. If `_reset()` is called mid-animation, `_animCurrent` gets set
to 0 and `_animating` to false, but the flying rAF step may fire once more and draw a stale
value. Minor visual glitch only.

---

### M5 — `CycleTimer._stop()` starts a `setInterval` for countdown but `_start()` resets it correctly

No interval leak: both `_start` and `_stop` guard with `if (this._interval) clearInterval(...)`.
`_clearAll` also cleans up. This is fine.

---

### M6 — `_updateCinematicOverlay` shadows the outer `ctx` variable name

`agent_network.js` line 1129: `function _updateCinematicOverlay(ctx)` — parameter named `ctx`
shadows the module-level canvas rendering context `ctx` (line 85). Since this function only
touches DOM elements (`getElementById`), it never actually uses the canvas context, so there
is no functional bug. But it is confusing and would become a bug if canvas operations were
ever added here.

---

### M7 — `_layoutNodes` calls `nodes.filter(n => n.tribe === node.tribe)` inside the outer loop

In `_layoutNodes()` (line 206-222), for each of 24 nodes, it filters the full 24-element
`nodes` array to find tribe-mates. This is O(n²) = 576 iterations on every resize/layout.
Negligible cost for 24 nodes, but could be a named constant cache.

---

### M8 — Cinematic mode toggle mid-cycle: state is preserved correctly

`_toggleCinematic()` flips `isCinematic`, toggles a body class, then calls `setTimeout(50,
_resize + _layoutNodes)`. The 50ms delay means a frame or two may draw at wrong dimensions.
During an active cycle (`dirty = true` constantly), this means at most 3 frames render with
stale dimensions. Acceptable. Node positions (`tx`, `ty`) are recomputed by `_layoutNodes` and
nodes lerp toward new targets. State (votes, directions, glow) is entirely preserved. No bug
here.

---

### M9 — `SignalHistory` and `StatsBar` both fetch `/api/stats` independently on `ws:connected` and `cycle:completed`

Two separate `fetch("/api/stats")` calls fire simultaneously on the same events. Minor
redundancy — could be unified into a single fetch shared between the two components.

---

## LOW

### L1 — Duplicate abbreviations in TRIBES (agent_network.js)

`TRIBES.technical.abbr` has `["VV","GG","DD","MM","LL","TT"]` — unique.  
`TRIBES.macro.abbr` has `["FF","FF","VV","GG","PP","BB"]` — `"FF"` repeated (Fed Fred / Flow Fiona).  
`TRIBES.strategists.abbr` has `["CC","SS","SS","SS","RR","SS"]` — `"SS"` for Spread Sam,
Scalp Steve, Swing Sarah, and Synthesis Syd. The abbreviation text drawn on canvas nodes is
ambiguous.

### L2 — `var` not used; `"use strict"` is present in all files — good

No `var` usage found. Strict mode declared at top of each file.

### L3 — `leaderboard.js` has a local `_esc` that duplicates the same function in `components.js`

Both implementations are identical. Not a bug, but a minor maintenance point.

### L4 — `_updateWsStatus` in swarm.js does unsafe property access on `dot` and `label`

Lines 161-166: `dot.className = ...` and `label.textContent = ...` execute without null
guards after `querySelector`. If `#ws-status` exists but lacks the child elements, this
throws. The outer `if (!el) return` guard checks the container but not the children.

### L5 — `ActivityLog._describe` uses `const` inside `switch` cases without block scope

Lines 653, 656, 659, 662, 665: `const mc`, `const flip`, `const vc`, `const c`, `const tc`
declared inside `switch` case branches without block (`{}`). In strict mode this is a
SyntaxError in some older environments and a linter warning in all. Wrap each case body in
`{}` braces.

### L6 — `_hex2rgba` called with every draw call — no memoization

`_hex2rgba` parses a hex string via `parseInt` on every call. With the same colors repeated
hundreds of times per frame, a small Map cache keyed on `hex+alpha` would avoid repeated
string parsing. Micro-optimization.

---

## Test Gaps

1. No frontend tests exist at all. Key logic with actual behavior risk:
   - `_barColor` ELO gradient interpolation (floating-point boundary at DEFAULT_ELO ±1)
   - `_eloClass` threshold logic
   - Agent ID lookup mismatches (the `putcall_pete` / `put_call_pete` bug would be caught by
     a simple `assert AGENT_TRIBE[id]` for each id in `scoring.KNOWN_AGENTS`)
   - `_hex2rgba` parsing correctness
   - WS reconnect backoff calculation

2. No integration test that the `leaderboard:updated` event from `Leaderboard._fetch` causes
   `AgentNetwork._applyEloToNodes` to update all 24 nodes (would have caught H1 directly).

---

## Verdict

**BLOCK on H1** (agent_id mismatch silently breaks ELO for one agent everywhere — canvas
scaling, tint, hover card, leaderboard row color). This is a data-correctness bug that is
live in production.

**BLOCK on H2** (per-frame shadowBlur at scale) only if mobile/low-end devices are a
deployment target. On desktop RTX 4090 it is invisible. On mobile it will cause dropped
frames and battery drain.

**H3** (ELO NaN badge) is a cosmetic rendering defect before first leaderboard load.
Fix is a 2-character change.

All other issues are MEDIUM or LOW and non-blocking for a single-user trading dashboard.

**The codebase does not need to be rebuilt.** The architecture is appropriate for the domain.
The CustomEvent bus is consistent, the IIFE scoping is clean, and XSS hygiene is solid.
The primary work needed is: fix the agent_id constant (one grep-and-replace), add `shadowBlur`
caching for performance, and add the ELO null guard. Estimated: 30-60 minutes of actual fixes.
