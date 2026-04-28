# Darwinian Scoring Review

## Summary

The Darwinian scoring system has a sound architectural foundation — ELO math is
standard, softmax weighting is reasonable, and the persistence layer works correctly
under normal conditions. However, it has one confirmed algorithmic bug (floor
renormalization does not converge in 10 iterations when a single agent dominates),
one semantic bug that will consistently mis-credit NEUTRAL voters, a permanent data-loss
race condition in outcome resolution, an agent ID mismatch (`put_call_pete` vs
`putcall_pete`) that silently drops 1 of 24 agents from ELO updates in the backtest,
two different and incompatible floor implementations across `scoring.py` and
`backtest/engine.py`, and a backtest whose claimed "+4-6%" improvement is an artefact
of baked-in synthetic accuracy differentials — not evidence the live system will improve.
The system should **not** be rebuilt, but it has five fixes that are mandatory before
relying on ELO weights for real trade decisions.

---

## CRITICAL findings (will lose money or corrupt data)

**[C1] Floor renormalization loop does not converge within 10 iterations under realistic
ELO spread.**
File: `swarmspx/scoring.py:278-283`

When one agent reaches a substantially higher ELO than all others (e.g. 2000 vs 1–50
for everyone else, which is achievable after ~150 signals with K=40), the softmax
produces one weight near 1.0 and 23 weights near 0. After floor-and-renorm, the
dominant agent's weight is pushed below 1.0, which frees some budget, but not enough
to lift 23 agents above `MIN_WEIGHT=0.02`. After all 10 iterations, 23 agents still
sit at ~0.01999, violating the floor. The loop exits with `all(w >= MIN_WEIGHT - 1e-9)`
— **this condition never triggers as True**, so the loop always runs all 10 rounds and
exits with weights that lie ~0.00005 below the floor. The `assert`-equivalent check
on line 283 never breaks the loop correctly.

Proven with ELO spread of {2000, 1×23}: after 10 iterations, min weight = 0.01999542,
which is below MIN_WEIGHT.

The backtest's `compute_weights` uses a mathematically correct one-shot formula
(`floor + remaining * raw_weight`) that always satisfies the floor. **The production
scorer uses the broken iterative version.**

Fix: Replace the iterative loop with the one-shot formula already proven in the
backtest engine:
```python
n = len(agent_ids)
total_floor = MIN_WEIGHT * n
remaining = 1.0 - total_floor
weights_arr = [MIN_WEIGHT + remaining * w for w in raw_weights]
total = sum(weights_arr)
weights = {aid: w / total for aid, w in zip(agent_ids, weights_arr)}
```

---

**[C2] NEUTRAL votes are always penalised — on wins AND on losses.**
File: `swarmspx/scoring.py:377,386`

In `process_signal_outcome`:
- On a `win` with `consensus_direction="BULL"`: `correct_direction = "BULL"`. An agent
  who voted `NEUTRAL` has `was_correct = ("NEUTRAL" == "BULL") = False`. It gets a loss
  deduction and `was_contrarian = True`. ELO drops.
- On a `loss` with `consensus_direction="BULL"`: `correct_direction = _opposite("BULL") =
  "BEAR"`. A `NEUTRAL` voter has `was_correct = ("NEUTRAL" == "BEAR") = False`. It again
  gets a loss deduction.

NEUTRAL voters are **always wrong** regardless of outcome, because `_opposite("NEUTRAL")
= "NEUTRAL"` is never the `correct_direction` when the signal resolves as win or loss
(those require a BULL or BEAR consensus). Any agent that hedges with a NEUTRAL vote
is permanently punished. In a 0DTE system where agents with genuine uncertainty should
abstain without penalty, this corrupts ELO rankings over time.

Fix: Treat NEUTRAL votes as abstentions — skip ELO update entirely for `NEUTRAL`
direction votes. Alternatively, count NEUTRAL as correct only when `outcome == "scratch"`.

---

**[C3] `put_call_pete` vs `putcall_pete` — agent silently receives no ELO credits in
backtest, and is excluded from `get_weights` in real system if any caller uses backtest
IDs.**
File: `swarmspx/scoring.py:69` vs `swarmspx/backtest/engine.py:11` vs
`config/agents.yaml:74`

The canonical ID in `agents.yaml` is `putcall_pete` (no underscore). `KNOWN_AGENTS` in
`scoring.py` contains `put_call_pete` (with underscores). `AGENT_IDS` in the backtest
engine uses `putcall_pete`. This means:
1. In the backtest, `putcall_pete`'s votes go through `update_elo` correctly (using the
   backtest's local ELO dict), but if anyone calls `credit_agent("putcall_pete", ...)`,
   the `if agent_id not in KNOWN_AGENTS` check silently returns at line 305 — no ELO
   update, no error.
2. The live system (`outcome_tracker.py`) fetches votes from the DB. The DB stores
   whatever ID the agent framework used. If the agent framework uses `putcall_pete`
   (from `agents.yaml`), that agent's ELO is never updated in production.
3. `get_weights` always returns a weight for `put_call_pete` (since it iterates
   `KNOWN_AGENTS`), but the actual live agent is `putcall_pete`. The weight is applied
   to a ghost ID; the real agent gets the equal-fallback weight.

Fix: Change `put_call_pete` to `putcall_pete` in `KNOWN_AGENTS` in `scoring.py` (or
vice versa, after confirming what the agent framework actually emits).

---

**[C4] Permanent ELO loss on process crash — `db.update_outcome()` called before
`_sync_to_db()`.**
File: `swarmspx/tracking/outcome_tracker.py:101` vs `swarmspx/scoring.py:398`

In `check_pending_signals`, the sequence is:
1. `self.db.update_outcome(signal["id"], outcome, pnl_pct)` — signal marked resolved.
2. `self.scorer.process_signal_outcome(...)` — ELO updated in memory.
3. (inside process_signal_outcome) `self._sync_to_db()` — ELO persisted.

If the process crashes or raises between steps 1 and 3, the signal is permanently
marked `win/loss` in the DB (no longer pending), but the ELO scores were never
persisted. The signal will never be re-processed because `get_pending_signals` filters
it out. Every such crash silently drops an ELO sample. Over many 0DTE trading days with
frequent restarts, this introduces systematic bias.

Fix: Persist ELO before marking the signal resolved, or use a DB transaction that
wraps both the outcome update and the ELO sync together.

---

## HIGH findings (logic bugs, wrong results, but recoverable)

**[H1] `process_signal_outcome` "loss → contrarians were right" assumption is flawed
for 0DTE options.**
File: `swarmspx/scoring.py:377`

The code defines: "loss → agents who voted BEAR when consensus was BULL were correct."
In 0DTE SPX options, a *loss* means the bought option expired worthless or was closed
at a loss. This can happen because:
- Direction was wrong (the assumption the code makes).
- Direction was right but timing was off (theta decay killed the option before the
  move occurred).
- Slippage / wide spread ate the premium.

If an agent voted BEAR on a BULL signal that was a loss purely due to theta (the market
went sideways), the BEAR voter is credited as "correct" even though their direction was
also wrong (it went sideways, not down). There is no systematic fix within pure ELO —
this is a fundamental limitation of mapping options P&L to directional correctness. At
minimum, the docstring should document this assumption and a scratch threshold should be
widened (currently only ±0.05% is scratch — that is extremely narrow for 0DTE where
even a 0.1% move can flip theta-dominated options between profit and loss).

**[H2] Backtest improvement is circular — baked-in accuracy differentials guarantee
the weighted system wins.**
File: `swarmspx/backtest/engine.py:80-95`

`_init_agents` explicitly assigns 1–2 "strong" regimes (accuracy 0.60–0.85) and 1–2
"weak" regimes (0.25–0.40) per agent. This creates the exact condition where ELO
excels: heterogeneous agents with stable regime-specific skill. Of course ELO-weighted
consensus then discovers and amplifies the strong agents.

When all accuracies are set to 0.5 (uniform coin-flip), the improvement collapses to
near-zero (tested: −0.2% on 500 signals). The claimed "+4–6%" improvement has zero
bearing on whether the live system will improve, because in live trading:
- Agent accuracy is unknown and non-stationary.
- Regimes shift.
- All 24 agents see the same LLM prompt, so their errors are correlated, not independent.

The backtest is valid as a **sanity check** ("ELO math works when agents have real
differential skill") but it **cannot** be cited as evidence of live improvement.

**[H3] Two incompatible floor implementations between production and backtest.**
File: `swarmspx/scoring.py:278-283` vs `swarmspx/backtest/engine.py:152-160`

Production uses the broken iterative loop (see C1). Backtest uses the mathematically
correct `floor + remaining * raw_weight` one-shot formula. This means the backtest
demonstrates a system that is slightly different from what runs in production. Specifically
the floor behavior post-convergence failure differs: production weights can sit at
~0.01999 vs backtest floor at exactly 0.020. Over hundreds of signals with dominated ELO
distributions, this divergence compounds.

**[H4] Tie-breaking in weighted consensus is arbitrary and undocumented.**
File: `swarmspx/simulation/consensus.py:119`

`max(weighted_sums, key=lambda d: weighted_sums[d])` on a dict with two equal float
sums is determined by iteration order (insertion order in Python 3.7+, which is
`defaultdict` insertion order — i.e. whichever direction was encountered first in the
votes list). In a 2-direction tie, the outcome depends on the order agents voted, which
is effectively arbitrary. No tie-breaking policy is documented. For a 0DTE system
where ties likely indicate genuine uncertainty, the correct response may be NEUTRAL/WAIT,
not a coin-flip directional trade.

**[H5] `weighted_agreement_pct` is inflated when `agent_weights` does not cover all
voting agents.**
File: `swarmspx/simulation/consensus.py:110-116`

`equal_fallback = 1.0 / len(votes)`. If `agent_weights` covers only `k < len(votes)`
agents and those weights sum to 1.0, the total weight in `weighted_sums` will be
`> 1.0` (known agents contribute 1.0, unknown agents contribute their fallback on top).
`weighted_agreement_pct = winner_weight / total_weight` normalises this away for the
direction selection, but the absolute value of `total_weight` is not 1.0, making
`weighted_agreement_pct` a misleading confidence metric. In the 4-vote example with
2 covered agents (weights 0.6+0.4=1.0), BULL gets 1.0 and BEAR gets 0.5, total=1.5,
so `weighted_agreement_pct=66.7%` — but the raw vote split was 50/50.

This is triggered in practice whenever a new agent is added at runtime before its ID
appears in the ELO scores (and therefore in `get_weights`'s output dict).

---

## MEDIUM findings (code smell, fragility, future bug risk)

**[M1] `_ensure_schema` swallows all exceptions with a bare `except Exception`.**
File: `swarmspx/scoring.py:157-158`

If the DB is read-only, out of disk space, or a permission error occurs, the exception
is logged and silently suppressed. All subsequent DB operations then fail with cryptic
errors. The pattern should re-raise after logging, or at minimum raise a
`RuntimeError("cannot initialise scoring schema")` to fail fast.

**[M2] `_sync_to_db` upserts all records in `_scores`, not just dirty ones.**
File: `swarmspx/scoring.py:192-220`

After a few dozen signals, `_scores` accumulates records for all active agent-regime
pairs. Every call to `_sync_to_db` (which happens after every resolved signal) upserts
all of them. In steady state with 24 agents × 5 regimes = 120 records, each resolution
does 120 upserts when only ~24 actually changed. Add a dirty-flag or set to track
modified keys.

**[M3] `_average_elo` uses `KNOWN_AGENTS` as the reference pool, not the active voting
agents.**
File: `swarmspx/scoring.py:237-242`

The "opponent ELO" in the ELO formula is the mean of all 24 known agents in the regime.
Agents with no data default to 1000. This is reasonable but means early signals (when
most agents have no data) treat everyone as if they face a 1000-ELO opponent, which is
accurate. However, as agents diverge, the average drifts, and an agent at 1050 facing an
average of 1040 (most agents still near 1000) gets less credit per correct answer than
is intuitive. Not a bug, but this makes K-factor tuning harder to reason about.

**[M4] `check_pending_signals` in `outcome_tracker.py` is `async` but calls
`_get_current_price()` synchronously.**
File: `swarmspx/tracking/outcome_tracker.py:46, 147-154`

`_get_current_price` calls `self.fetcher.get_snapshot()` — a potentially blocking HTTP
call — without `await`. If `fetcher` is an async client, this will not work. If it is a
sync client, it blocks the event loop during price fetching, stalling all other async
tasks. The method should be `async` and awaited, or the fetch should be offloaded with
`asyncio.to_thread`.

**[M5] `_is_eod` uses local system time without timezone awareness.**
File: `swarmspx/tracking/outcome_tracker.py:157-159`

`now.hour >= 16` assumes the server runs in US Eastern time. If deployed on a UTC server
(common for cloud), market close is at 20:00 UTC but the check fires at 16:00 UTC (noon
ET). All PM signals would be force-resolved 4 hours early. Use `pytz` or `zoneinfo` to
check ET explicitly.

**[M6] `get_leaderboard` aggregates wins/losses from the regime-filtered path
inconsistently.**
File: `swarmspx/scoring.py:459-473`

The normalisation pass at lines 459–473 handles both the per-regime and global paths,
but per-regime rows have a `"total"` key while aggregated rows have `"total_signals"`.
The `r.get("total") or r.get("total_signals", 0)` guard handles this, but adding a new
code path that uses either name without updating both branches will silently produce
`win_rate=0.0`. The inconsistent key naming is a latent bug.

**[M7] `consensus.py` has no type hints on public method signatures.**
File: `swarmspx/simulation/consensus.py:6-13`

`extract`, `detect_herding`, `_construct_trade_setup`, `_aggregate_trade_ideas` all lack
return type annotations. Given the dict-heavy return types, this makes it easy to miss
key renames like the `"total"` vs `"total_signals"` issue above.

---

## LOW findings (style, naming, minor refactor)

**[L1] `BacktestEngine.update_elo` duplicates K-factor logic from `scoring._k_factor`.**
File: `swarmspx/backtest/engine.py:182-187`

Inline if/elif instead of calling the shared `_k_factor` function. If K-factor schedule
changes in `scoring.py`, the backtest will silently use stale values.

**[L2] `AgentProfile.random` classmethod in backtest is unused and inconsistent with
`_init_agents`.**
File: `swarmspx/backtest/engine.py:32-37`

`_init_agents` does not use `AgentProfile.random`; it constructs profiles directly.
Dead code that suggests an earlier design.

**[L3] Magic numbers in `_compute_trend`.**
File: `swarmspx/scoring.py:578-580`

Thresholds 1010 and 990 are inline literals. These should be named constants at module
level (e.g. `TREND_IMPROVING_THRESHOLD = 1010.0`).

**[L4] `backtest/engine.py` missing type hints throughout.**
File: `swarmspx/backtest/engine.py` (all methods)

`run`, `run_monte_carlo`, `weighted_consensus`, `equal_weight_consensus` have no return
type annotations.

---

## Test gaps

1. **NEUTRAL vote mis-crediting**: No test verifies that a NEUTRAL vote on a win is not
   penalised. `test_vote_fields_stored_correctly` stores NEUTRAL but never runs it
   through ELO.

2. **`put_call_pete` / `putcall_pete` ID consistency**: No test cross-checks
   `KNOWN_AGENTS` against `AGENT_IDS` or `agents.yaml`. This is the kind of regression
   a one-line set-equality test would catch permanently.

3. **Floor convergence failure**: `test_weight_floor_enforced` only tests one agent at
   ELO=1. It does not test the dominant-ELO scenario (one agent at 2000, 23 at 1) which
   triggers the non-convergence.

4. **Crash recovery / ELO atomicity**: No test simulates `db.update_outcome` succeeding
   then `_sync_to_db` failing, and verifies whether the signal is re-processable.

5. **`weighted_agreement_pct` with partial weight coverage**: No test exercises the case
   where `agent_weights` covers fewer agents than `votes`.

6. **NEUTRAL consensus outcome**: No test calls `process_signal_outcome` with
   `consensus_direction="NEUTRAL"` and verifies sensible behaviour.

7. **`test_backtest_weighted_beats_equal` has threshold >= -2.0**: This passes even if
   weighted is 1.9% worse than equal. Needs `> 0` to be meaningful.

8. **Backtest with uniform accuracy baseline**: No test verifies that with all agents at
   50% accuracy, improvement is near zero (i.e. the system isn't generating phantom gains
   from RNG artefacts).

9. **Timezone-aware EOD check**: No test for `_is_eod` in UTC vs ET.

10. **ID mismatch after YAML change**: No integration test loads `agents.yaml` and
    cross-checks all IDs against `KNOWN_AGENTS`.

---

## Verdict

**Refactor — do not rebuild, but fix C1–C4 before relying on ELO weights for trades.**

The core ELO mathematics, DB persistence, and softmax weighting are all correct. The
architecture (regime-scoped ELO, softmax → vote weight, contrarian bonus) is sound. But
four critical bugs mean the system as shipped is not safe to use for live weighting:

- C1 (floor bug) means low-ELO agents silently get below-floor weights after the ranking
  diverges — the promised minimum exposure is broken.
- C2 (NEUTRAL penalty) means any agent that adds genuine uncertainty signal by voting
  NEUTRAL is systematically down-ranked, which corrupts the leaderboard over time.
- C3 (ID mismatch) means Put-Call Pete's live votes never update its ELO — one of your
  24 agents is a ghost.
- C4 (crash ordering) means every restart loses one batch of ELO credits permanently.

All four are localised, one-function fixes. C1 and C3 together take about 10 lines.
After fixing them, the system is sound enough to run in shadow mode (computing weights
without acting on them) for 2–4 weeks of live signals before trusting it with trade
sizing decisions. The backtest showing "+4–6%" improvement should be treated as a
*sanity check* that the ELO math works, not as a live performance projection.
