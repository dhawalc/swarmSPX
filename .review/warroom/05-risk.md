# SwarmSPX — Risk & Behavioral Audit
**Author**: Risk seat (Taleb school)
**Subject**: 24-agent SPX 0DTE swarm, $25k bankroll, solo retail
**Verdict**: The architecture is sound. The danger is not in the model. It is in the **path** the model puts you on, the **regime** it does not yet detect, and the **trader** it cannot override.

---

## 0. The thesis you do not want to hear

A trading system with positive expectancy on paper goes bankrupt in production for one of three reasons, and only three:

1. **Path-dependent ruin** — the equity curve hits zero before the law of large numbers can save it.
2. **Regime change** — the distribution that produced the edge stops producing it, and the model keeps trading anyway.
3. **The operator** — a solo retail trader overrides the system at the worst possible moment.

SwarmSPX, as currently built, is exposed to all three. The 13 CRITICAL bugs in `00-SUMMARY.md` are real engineering risks but they are not the largest risks. The largest risks are silent, statistical, and behavioral. This document is about those.

> "The test of a first-rate intelligence is the ability to hold two opposed ideas in mind at the same time and still retain the ability to function." — F. Scott Fitzgerald, quoted by Soros on fallibility.
> Hold these two: *the system has edge*, AND *the system will try to kill you*.

---

## 1. Why most "edge" systems blow up

Run the failure tree backward from a blown account. The taxonomy:

| Failure mode | Mechanism | SwarmSPX exposure |
|---|---|---|
| **Regime change** | Distribution shifts; agents trained on 2024-2025 vol see 2027 panic vol | High — no regime gate exists yet |
| **Model drift** | ELO weights ossify around stale agent skill; live skill decays | High — `scoring.py` has no decay term |
| **Position-size creep** | "I'm hot, let me size up" → one bad day wipes month | Critical — no enforced sizing |
| **Correlated drawdowns** | Three losses in a row are not independent — they came from the same regime miss | High — no consecutive-loss circuit breaker |
| **Leverage stack** | 0DTE *is* leverage. Adding margin or position sizing on top compounds | Medium — Alpaca paper not wired yet, but the temptation is real |
| **Vol blow-up** | VIX +10 in a day; gamma flips; option pricing breaks the agent's mental model | High — agents don't know IV percentile |
| **Confidence illusion** | "Backtest shows +4-6% improvement" → real number is unknown (synthetic data) | Critical — flagged in `00-SUMMARY` H1 |
| **Operator override** | Trader skips a "scary" trade that was the edge, takes a "feel-good" trade that wasn't | Universal — the only fix is automation |

The point: **a system with 60% positive expectancy in expectation can deliver -100% in path** if any one of these failure modes hits during a drawdown. Drawdowns and failure modes are correlated. That is the trap.

---

## 2. The math of 0DTE asymmetry done right

You want asymmetric: 35% win rate, 4:1 average winner-to-loser. Good. Compute the expectancy:

```
E[trade] = 0.35 × (+4R) + 0.65 × (-1R) = +1.40 - 0.65 = +0.75R per trade
```

That is real edge — *if you can survive to realize it*. Now the path math.

**Probability of N consecutive losses at p_loss = 0.65**:
```
P(2 in a row) = 0.4225  (≈ once a week if you trade 5×)
P(3 in a row) = 0.2746  (≈ once every 2 weeks)
P(4 in a row) = 0.1785  (≈ once every 3 weeks)
P(5 in a row) = 0.1160  (≈ once a month)
P(6 in a row) = 0.0754  (≈ once every 6 weeks)
P(7 in a row) = 0.0490  (≈ once every 2 months)
P(8 in a row) = 0.0319  (≈ once a quarter — yes, you will see this)
P(10 in a row) = 0.0135 (≈ once a year)
```

A 6-loss streak is *normal*, not catastrophic. Now overlay position sizing.

**Drawdown from N losses at risk-per-trade r%**:
```
DD(N losses at r%) = 1 - (1-r)^N
```

| Risk per trade | 5 losses | 8 losses | 10 losses | Time to 60% DD |
|---|---|---|---|---|
| 1% | 4.9% | 7.7% | 9.6% | ~90 losses |
| 2% | 9.6% | 15.0% | 18.3% | ~45 losses |
| 5% | 22.6% | 33.7% | 40.1% | ~18 losses |
| 10% | 41.0% | 56.9% | 65.1% | ~9 losses |
| 20% | 67.2% | 83.2% | 89.3% | ~4 losses |

**At $25k bankroll, sizing 10% per trade = one normal losing streak away from ruin.**

This is the single most important table in this document. Ergodicity (Section 7) means the *expected* return is irrelevant if you cannot survive the path. **Cap risk per trade at 1-2%.** Yes, even on the "obvious" trades. Especially on those.

> "You do not gain by taking the average. You gain by surviving." — Taleb, *Skin in the Game*.

---

## 3. Kelly, fractional Kelly, and why full Kelly will bankrupt you

Kelly criterion for a binary trade:
```
f* = (p × b - q) / b
   = (0.35 × 4 - 0.65) / 4
   = (1.40 - 0.65) / 4
   = 0.1875  → 18.75% of bankroll per trade at full Kelly
```

**Full Kelly is correct in theory and lethal in practice.** Three reasons:

1. **Estimation error**: your real win rate is not 35%. It is 35% ± 8%. If true win rate is 27%, full Kelly is *negative*. The estimator is overconfident in proportion to how much it bets.
2. **Non-stationarity**: yesterday's 35% is today's 28%. Full Kelly ignores the regime.
3. **Drawdown profile**: full Kelly produces an expected 30-50% drawdown *as the standard outcome*. Not the tail — the expectation. No human survives that emotionally.

**Fractional Kelly schedule** (institutional standard):

| Fraction | Sizing | Use case |
|---|---|---|
| 1.00 Kelly (18.75%) | Full | Never. This is for textbooks. |
| 0.50 Kelly (9.4%) | Half | Aggressive prop with hard kill switch |
| 0.25 Kelly (4.7%) | **Quarter — institutional standard** | What you should do |
| 0.10 Kelly (1.9%) | Tenth | When uncertain about your own win rate (i.e. always, especially first 6 months) |

**Recommendation for SwarmSPX**: start at **0.10 Kelly = 1.9% per trade = ~$475 risk on $25k**. Increase to 0.25 Kelly only after 100+ resolved live signals confirm the win rate empirically. Do not go above 0.25 Kelly ever.

Edward Thorp ran his fund at ~0.30 Kelly and considered himself aggressive. You are not Thorp. López de Prado in *Advances in Financial Machine Learning* makes the same point with sharper teeth: "Kelly is for known distributions. Markets do not give you known distributions."

---

## 4. Regime detection — the most under-rated edge

A 65% win rate in normal vol becomes 35% in panic vol. **The single highest-EV piece of code you can write is the one that decides not to trade today.**

**Regime indicators** (all available from your data sources):

| Indicator | Source | Calm regime | Panic regime |
|---|---|---|---|
| **VIX absolute level** | Schwab `$VIX` | < 18 | > 25 |
| **VIX term structure** | Schwab futures or Tradier | Contango (VX2-VX1 > 0) | Backwardation (VX2-VX1 < 0) |
| **VIX 1-day delta** | Schwab daily | < +2 | > +4 |
| **Realized-vs-implied gap** | Compute from SPX 5-day RV vs ATM IV | RV ≈ IV | RV > IV (vol underpriced → trend regime) |
| **SPX 1-day move** | Schwab | < 0.7σ | > 1.5σ |
| **Breadth (advance/decline)** | Finnhub (when wired) | A/D > 1.0 | A/D < 0.4 |
| **Cross-asset correlation** | Compute from sector ETFs | Diverse | All correlated → systemic risk |
| **Put/call ratio** | Tradier | 0.7-1.0 | > 1.3 |
| **Skew** | Tradier 25Δ put / 25Δ call IV | < 1.10 | > 1.20 |

**Simple regime classifier** (3-bucket):
```python
def classify_regime(vix, vix_d1, vix_term, spx_sigma, ad_ratio):
    score = 0
    if vix > 25: score += 2
    if vix > 30: score += 1
    if vix_d1 > 4: score += 2
    if vix_term < 0: score += 2  # backwardation
    if abs(spx_sigma) > 1.5: score += 1
    if ad_ratio < 0.4: score += 1
    if score >= 5:  return "PANIC"     # don't trade, or trade size /4
    if score >= 2:  return "ELEVATED"  # trade size /2
    return "NORMAL"                    # full size
```

**Hard rule**: if regime == PANIC, the system **does not trade**. Or trades 0.25× normal size if you cannot resist. Backtest by regime separately. The aggregate 60% win rate may hide a 75% / 35% split across regimes — and you are losing exactly when it hurts most.

> "The market can stay irrational longer than you can stay solvent." — Keynes, attributed.
> Translation: even when the model is right *eventually*, the path may not let you wait.

---

## 5. Kill-switch architecture — circuit breakers in code, not in willpower

Willpower is a depleting asset and it depletes fastest exactly when you need it. Hard-code the limits.

```python
# swarmspx/risk/circuit_breakers.py

@dataclass
class RiskState:
    bankroll: float
    starting_bankroll_today: float
    starting_bankroll_week: float
    starting_bankroll_month: float
    consecutive_losses_today: int
    last_loss_2sigma_at: datetime | None
    paused_until: datetime | None

DAILY_LOSS_LIMIT_PCT     = 0.03   # 3% of bankroll
WEEKLY_LOSS_LIMIT_PCT    = 0.06   # 6%
MONTHLY_LOSS_LIMIT_PCT   = 0.10   # 10%  ← stop. period.
CONSECUTIVE_LOSS_LIMIT   = 3      # 3 losses in a session = done for the day
TWO_SIGMA_COOLOFF_HOURS  = 2

def check_circuit_breakers(state: RiskState, now: datetime) -> tuple[bool, str]:
    if state.paused_until and now < state.paused_until:
        return False, f"PAUSED until {state.paused_until.isoformat()}"

    daily_loss = (state.starting_bankroll_today - state.bankroll) / state.starting_bankroll_today
    if daily_loss >= DAILY_LOSS_LIMIT_PCT:
        return False, f"DAILY LOSS LIMIT HIT ({daily_loss:.1%})"

    weekly_loss = (state.starting_bankroll_week - state.bankroll) / state.starting_bankroll_week
    if weekly_loss >= WEEKLY_LOSS_LIMIT_PCT:
        return False, f"WEEKLY LOSS LIMIT HIT ({weekly_loss:.1%})"

    monthly_loss = (state.starting_bankroll_month - state.bankroll) / state.starting_bankroll_month
    if monthly_loss >= MONTHLY_LOSS_LIMIT_PCT:
        return False, f"MONTHLY LOSS LIMIT HIT — STOP TRADING UNTIL NEXT MONTH"

    if state.consecutive_losses_today >= CONSECUTIVE_LOSS_LIMIT:
        return False, f"{state.consecutive_losses_today} consecutive losses — DONE FOR THE DAY"

    if state.last_loss_2sigma_at and now - state.last_loss_2sigma_at < timedelta(hours=TWO_SIGMA_COOLOFF_HOURS):
        return False, f"2-sigma loss cooldown — wait until {state.last_loss_2sigma_at + timedelta(hours=2)}"

    return True, "ok"
```

Place this check **inside `engine.run_cycle()`** before the report is dispatched. If it fails, the report is logged but **no Telegram trade card** is sent. The trader cannot trade what they did not see.

This is the single most important defensive code in the whole system.

---

## 6. Behavioral guardrails for solo retail

This is the section that decides whether you keep your money. The signal does not.

### Pre-committed position size (Ulysses contracts)
At the start of each session, the system writes a JSON file with that day's position size. Mid-session, the size cannot be changed. Want to size up? You can. Tomorrow.

```python
# swarmspx/risk/sizing_lock.py
def lock_session_sizing(bankroll: float, regime: str) -> float:
    base = 0.019  # 0.10 Kelly
    multipliers = {"PANIC": 0.0, "ELEVATED": 0.5, "NORMAL": 1.0}
    size_pct = base * multipliers[regime]
    Path(f"runtime/session_size_{date.today()}.lock").write_text(
        json.dumps({"size_pct": size_pct, "regime": regime, "bankroll": bankroll})
    )
    return size_pct
```

### No discretionary override
The system trades. You don't. If you find yourself wanting to "skip this one" or "add to this one," that is the bias talking. The audit log records every override; review weekly.

### Daily review ritual, no mid-session second-guessing
Before market open: read yesterday's log. After close: write today's log. **During market hours: do not look at P&L.** Set the dashboard to hide P&L between 9:30 and 16:00. The "screen-time → P&L" inverse correlation is one of the most robust findings in retail trading research: more screen time, worse outcomes.

### Loss-cluster rule
3 losses in one session = stop. No exceptions. No "let me just try the 11:30 trade." This is the exact moment your brain is *certain* the next one will win, and that is exactly when you are most wrong.

### The 24-hour rule for system changes
Want to add a custom agent, change a threshold, modify regime gates? Write the change down, sleep on it, implement tomorrow. Trading systems should change in committed git diffs at 9 PM, never in `vim` at 14:32.

---

## 7. The ergodicity trap

> "Time-average ≠ ensemble-average for non-ergodic processes." — Ole Peters, *Ergodicity Economics*. Taleb makes the same point in *Skin in the Game*: the path matters because you only have one life.

If 100 traders each trade your 60%-positive-expectancy system for one year:
- The **ensemble average** return is high.
- The **time average** for any single trader is much lower.
- The **median trader** loses money.
- A subset goes bankrupt.

Why? Because losses compound multiplicatively. A 50% loss requires a 100% gain to recover. Markets do not provide symmetric paths.

**Implication for SwarmSPX**: every backtest number you see is an ensemble statistic. Your *experience* will be a single path through that ensemble. Prepare for the possibility that you draw a bad path even if the system has edge.

The defenses are all in this document already: small Kelly fraction, regime gates, kill switches, no leverage, no override. Together they pull the time-average closer to the ensemble-average. Without them, you are gambling that you are the lucky path.

---

## 8. Antifragile design — make the system better when it loses

Per Taleb, antifragile is *not* robust. Robust survives. Antifragile *gains from disorder*. Build feedback loops where losses make the system *smarter*:

### Auto-adjust K-factor on drawdown
```python
def adjust_elo_k(current_drawdown_pct: float) -> int:
    if current_drawdown_pct > 0.10: return 48  # high learning rate when wrong
    if current_drawdown_pct > 0.05: return 24
    return 16  # default — slow learning when winning (preserve edge)
```

### Auto-reduce size on regime change
When `classify_regime()` flips from NORMAL to ELEVATED, multiply position size by 0.5 for 5 trading days even if it flips back.

### Auto-revalidate on Sharpe decay
Compute rolling 30-day Sharpe. If it drops below 0.8× the trailing 90-day Sharpe, **automatically halt trading and trigger a backtest re-run** on the last 6 months. If the backtest shows the system would have lost on recent regime, you have detected edge decay.

### Auto-pause on data anomaly
If `$SPX` quote is > 3σ from VWAP, or option chain has > 20% missing strikes, or VIX moves > 5 points in 5 minutes — pause. Wait for human acknowledgment. Bad data → bad signals → real money lost.

### Auto-notify on edge decay
Telegram alert when the live 30-trade rolling win rate diverges by > 10 percentage points from the backtest baseline. Either the model is broken, the regime shifted, or — most likely — the backtest was overfit (per `00-SUMMARY` H1).

The pattern: **the system does more work when it is hurting.** That is antifragility.

---

## 9. Common retail blow-up modes — code defenses against each

| Blow-up mode | Symptom | Code defense |
|---|---|---|
| Doubling down after losses | Position size up after a loss | `enforce_session_size()` lock; size set at open, cannot increase |
| Martingale-up after wins | "Hot streak, let's press" | Same lock — sizing changes only between sessions |
| Strategy-switching after losses | Manually overrides STRAIGHT → CONDOR | Lock strategy by regime classifier; manual override requires writing a justification to a file |
| Trading against the system | "The agents say BULL but I think BEAR" | Disable manual entry; trades only via Telegram tap-to-execute that pre-fills the agent's call |
| Skipping "scary" trades | Pass on the high-conviction signal that *felt* wrong | Auto-execute on conviction ≥ threshold; manual skip requires post-trade justification audit |
| Revenge trading | After a loss, take the next setup that "looks like" the previous winner | Cooldown: no new trade within 30 min of a loss |
| Holding losers | "It'll come back" — exits abandoned | Hard time stop: 0DTE always exits 15 min before close, no exceptions |
| Cutting winners | Take 1.5x because "it might give back" | Pre-defined exit logic; profit target locked at trade entry |
| Overtrading | 5 trades a day instead of 2 | Max trades per session enforced (3) |
| Adding leverage | Trading on margin | Refuse to wire margin account; cash only |

The pattern again: **automate the discipline you cannot enforce in real time.** Your future self at 14:32 with a 4% drawdown is not a reliable agent.

---

## 10. The honest Sharpe / DD / ruin-probability targets

**Insist on these numbers from 200+ resolved live signals before scaling size:**

| Metric | Minimum acceptable | Target | Reject if |
|---|---|---|---|
| Win rate (realized) | ≥ 33% | ≥ 38% | < 30% over 100 trades |
| Avg winner / avg loser | ≥ 3.0× | ≥ 4.0× | < 2.5× |
| Realized expectancy per trade | ≥ +0.5R | ≥ +0.75R | < +0.3R |
| **Sharpe (annualized, after costs)** | **≥ 1.2** | **≥ 1.8** | **< 0.8** |
| Sortino | ≥ 1.5 | ≥ 2.5 | < 1.0 |
| Max drawdown observed | ≤ 25% | ≤ 18% | > 35% |
| Calmar (CAGR / max DD) | ≥ 1.5 | ≥ 3.0 | < 1.0 |
| Ulcer Index | ≤ 8 | ≤ 5 | > 15 |
| Distinct regime tested | ≥ 2 (calm + elevated) | + 1 panic | only calm |
| Skill stationarity (Sharpe drift over 6 months) | ≤ 30% decay | ≤ 15% | > 50% |

**Ruin probability target**: at chosen sizing, Monte-Carlo simulated probability of -50% drawdown over 12 months should be **< 5%**. If you cannot get under 5%, your sizing is too aggressive.

**Pre-go-live walkforward**:
- 90 days paper trading (Alpaca, already configured)
- 50+ live signals reviewed against actual option P&L (per `00-SUMMARY` #1 fix)
- Two distinct regimes observed (e.g., one VIX < 18 week, one VIX > 22 week)
- All circuit breakers fired at least once in paper to verify they work

Until those four are met, trade $0.

---

## Closing word from the risk seat

The agents are clever. The architecture is clean. The bugs are fixable. None of that is what kills a retail 0DTE account.

What kills the account is: 4 losses in a row on a Tuesday, a missed regime gate on the following Friday's CPI print, an override at 14:50 that "felt like" the morning's setup, and a position size that crept from 2% to 6% over a hot week. Six weeks later: -68% drawdown, and the trader is now revenge-trading lottos at 3 PM with what's left.

You prevent that with **code, not character**. Lock the sizing. Gate the regime. Fire the kill switch. Forbid the override. Then trust the system to do its job, and use your discretion only on whether the system itself is allowed to run.

Soros' fallibility doctrine applies twice over: every market participant including you operates on a flawed model, and the act of trading reflexively changes the very distribution you are trying to predict. The defense is not a better model — it is hard-coded humility about the model you have.

> "Mediocristan: the law of large numbers works.
>  Extremistan: the law of large numbers needs you to *be alive* to work."
> — Taleb, *The Black Swan*.
> 0DTE is Extremistan. Build accordingly.

---

# Behavioral Audit Checklist

**Before each live session, answer YES to all 15. One NO = paper trade today, not live.**

1. Have I read yesterday's trade log and noted any rule violations?
2. Is my session position size locked in `runtime/session_size_<date>.lock` and untouched?
3. Has the regime classifier been run, and am I trading the size it dictates (not what I "feel" today)?
4. Are daily / weekly / monthly loss limit counters current and visible?
5. Have I had at least 7 hours of sleep, no alcohol since dinner, and eaten before market open?
6. Am I free of pending personal stress — argument, illness, money pressure outside trading — that would distort decisions?
7. Has the kill-switch test passed in this session's pre-flight (synthetic loss → trigger fires → no trade dispatched)?
8. Is the dashboard configured to **hide intraday P&L** between 9:30 and 15:30?
9. Is the Telegram trade card the only entry path — no manual order entry tab open?
10. Am I committed to the 3-loss daily stop, *including* the trade I'm sure will recover?
11. Have I confirmed I will not size up mid-session under any circumstance?
12. Is my position size ≤ 2% of bankroll per trade, regardless of conviction?
13. Have I confirmed I will not skip a system-flagged trade because it "feels risky"?
14. If I take a 2-sigma loss, will I respect the 2-hour cooldown without rationalizing around it?
15. Am I prepared, emotionally, to lose every dollar at risk today and not change a single rule tomorrow?

If any answer is "kind of" or "I think so" — that is a NO. Paper trade. Tomorrow is another day.
