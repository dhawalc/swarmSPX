# SwarmSPX War Room — Master Battle Plan

**Convened:** 2026-04-27
**Specialists:** Quant (Renaissance-school) · Market Maker (Citadel-school) · ML Researcher (DeepMind-school) · Systems Architect · Risk Manager (Taleb-school) · Heretic · Alt-Data Lead (Point72-school)

---

## The Unanimous Verdict

**The architecture is sound. The asset choice is questionable. The data is a paper bag. The labels are wrong. The backtest is fake. None of these require a rewrite. All of them can be fixed in 6 months for under $5k all-in.**

What separates SwarmSPX from a money-making machine is not lines of code. It is the absence of seven things every prop shop has and no retail tool ships:

1. **The right label** (option P&L, not SPX move)
2. **A point-in-time feature store** (no lookahead)
3. **An honest event-driven backtester** with realistic slippage
4. **Real flow + dealer positioning data** (DIY GEX from CBOE OI)
5. **A regime gate** that blocks trading in the wrong vol environment
6. **Kelly-fractioned position sizing locked at session open**
7. **A multi-trigger kill switch** in code, not in willpower

---

## What Each Specialist Said (1-line each)

| Specialist | Headline |
|---|---|
| **Quant** | LLM swarm is a narrator pretending to predict. Real edges are boring: VRP harvest, post-FOMC drift, OpEx pin. Fix label, ship LightGBM. |
| **Market Maker** | The agents debate in the dark because they can't see what dealers see. Build DIY GEX from free CBOE OI. That's $199/mo SpotGamma value for $0. |
| **ML** | LLM swarm is the cortex, not the alpha. Brain = LightGBM + conformal prediction. Cortex = LLMs parsing FOMC/news into structured features. |
| **Architect** | 5 missing subsystems are existential: feature store, backtester, risk gate, reconciliation, kill switch. Layer, don't rebuild. |
| **Risk** | Edge is necessary; survival is sufficient. Fractional Kelly + regime gate + kill switch in code. 0.10 Kelly on $25k = ~$475/trade max. |
| **Heretic** | SPX is the wrong arena — Citadel beats you. Single-name 0DTE on NVDA/TSLA has more text-narrative edge. Reward "stay out" signals. |
| **Data** | The model isn't the bottleneck — the eyes are. $525/mo (SpotGamma + Polygon + UW + News) is the steepest cost-per-IR jump in the landscape. |

---

## The 12 Highest-Conviction Moves (consensus across ≥2 specialists)

### Tier 0 — Stop the Bleeding (Week 1)
**Existential. No skipping.**

1. **Fix OutcomeTracker to measure option P&L, not SPX move.** *(Quant + ML + Architect)* — Every ELO score and every model trained downstream is currently learning the wrong objective. Until this is fixed, all optimization is theatre.

2. **Throw away current ELO data.** Once #1 is done, every score in the DB is noise. Rerun from clean.

3. **Fix the agent_id mismatch (`put_call_pete` vs `putcall_pete`).** *(Quant + Architect)* — 15 min change, blocks downstream issues. One agent currently never gets ELO updates.

4. **Wrap `engine.run_cycle` in try/finally.** *(Architect)* — Without this, one bug locks the trigger guard at "running" until restart.

### Tier 1 — Build the Spine (Month 1)

5. **Point-in-time feature store with two timestamps (`as_of_time`, `available_time`).** *(Architect + ML + Quant)* — The discipline that eliminates 90% of backtest fraud. Without this, every other improvement is built on sand.

6. **Honest event-driven backtester with slippage model.** *(Quant + ML + Architect)* — Replay 12 months of real SPX through the current swarm. Honest Sharpe number for the first time. Reference: López de Prado walk-forward protocol.

7. **DIY GEX engine from free CBOE OI.** *(Market Maker + Data)* — `swarmspx/dealer/gex.py`. Compute per-strike dealer gamma, surface gamma-flip / call-wall / put-wall as structured context. Replaces $199/mo SpotGamma. **3-day build, single highest-leverage data move.**

### Tier 2 — Build the Edge (Month 2-3)

8. **News-to-vol pipeline with Haiku 4.5.** *(Data + ML)* — Real-time headline scoring → ATM IV change in next 60s. Trade: long ATM straddle when predicted IV pop > +5% AND realized < ATM IV. ~$50/mo Anthropic budget. The asymmetry is large because most news is already priced.

9. **LightGBM directional model with isotonic + conformal calibration.** *(Quant + ML)* — Microstructure features + GEX + regime + news score → direction probability with valid coverage guarantees. Conformal lower bound feeds Kelly sizing.

10. **Repurpose the LLM swarm.** *(ML + Heretic)* — Stop asking 24 agents to vote on direction. Have them parse FOMC/earnings/news into structured features and produce auditable rationales. Treat them as cortex, not brain.

### Tier 3 — Survive the Edge (Month 3-4)

11. **Regime gate.** *(Risk + ML + Quant)* — VIX > 25 OR term backwardation OR VIX-d1 > +4 → system does not trade. A 65% strategy in calm regime becomes 35% in panic. Aggregate stats hide the split.

12. **Fractional Kelly with hard sizing lock + multi-trigger kill switch.** *(Risk + Architect)* — 0.10 Kelly = ~$475/trade max on $25k. Position size written to daily JSON lock at session open, immutable mid-session. Daily 3% / weekly 6% / monthly 10% loss bands hardcoded. 3-consecutive-loss session stop. Discipline in code, not willpower.

---

## Three Genuinely Novel Bets (not consensus, but defensible)

### A. **The Adversarial Swarm** *(Heretic)*
Train a parallel 24-agent counter-swarm whose only job is to kill the trade. Execute only when no devastating objection survives.
- Every "AI trading" product is an oracle ensemble; **none are adversarial**
- Naturally filters toward capacity-arb and event-harvesting trades — the only retail edges that exist
- Steelmanning-as-edge

### B. **Single-Name 0DTE Pivot** *(Heretic)*
SPX is the most efficient market on earth. Citadel beats you there. Single-name 0DTE on NVDA/TSLA/AAPL has:
- 100x more text-narrative for LLMs to chew on
- $0.50 contracts let you run real feedback loops in weeks not years
- Far less institutional competition
- Keep SwarmSPX as the public brand — make single-names the actual P&L engine

### C. **LLM-Maintained Causal Regime DAG with Conformal Kelly** *(ML)*
- No quant shop runs swarms
- No LLM-trading project bothers with conformal prediction
- The combination — swarm-built causal DAG → regime probability → conformal interval → Kelly on the *lower bound* — is genuinely unbuilt in 2026
- Flagship moonshot bet

---

## What to Kill on Day One

Six features in the current build that look impressive but are dead weight:

1. **Custom agents** — cute, no edge contribution, adds complexity to scoring
2. **Voice mode (v1.3 roadmap)** — pure vanity, no P&L impact
3. **AOMS memory module** — undocumented, blocks event loop, optional anyway
4. **The "+4-6%" backtest claim** — circular reasoning. Stop saying it publicly.
5. **3-round agent debate at 24 agents** — most of the IR is in round 1; rounds 2-3 just amplify correlation. Cut to round 1 + a smaller "objector" cohort.
6. **The leaderboard panel as a primary surface** — currently displays meaningless ELO. Hide until Tier 1 is complete.

---

## The Money Math

**$25k starting capital.** At 0.10 Kelly with documented edge:
- ~$475 max risk per trade
- ~3-5 trades/week
- 30%+ drawdowns are routine; size for 60% drawdowns to survive
- Realistic 12-month outcome with real edge: **1.2-1.5x SPY return at 2-3x volatility**
- Without real edge: blow up in 6-9 months, statistically certain

**Data spend tiers:**

| Tier | Monthly | What you get |
|---|---|---|
| Free | $0 | CBOE OI (DIY GEX), FRED, EDGAR, Twitter scraping, Reddit, Treasury auctions |
| Lean | $200 | + Polygon options + Anthropic Haiku budget + NewsAPI |
| Real | $525 | + SpotGamma Standard + Unusual Whales basic |
| Pro | $2,000+ | + Polygon Pro + LiveVol + professional flow |

**Recommended:** start at Lean ($200/mo), upgrade to Real ($525/mo) once Tier 1 backtester proves edge.

**Compute:** $0 — RTX 4090 at home + €4/mo VPS = total infrastructure budget.

---

## The 6-Month Operating Plan

| Phase | Time | Focus | Decision Gate |
|---|---|---|---|
| **0** | Week 1 | Fix Tier 0 critical bugs (OutcomeTracker, agent IDs, exception handling) | Tests green; clean state |
| **1** | Month 1 | Feature store + honest backtester + DIY GEX | Backtest shows real Sharpe (any number, just honest) |
| **2** | Month 2 | LightGBM + conformal + news-to-vol pipeline | OOS Sharpe > 1.0 across ≥60% of walk-forward windows |
| **3** | Month 3 | Regime gate + Kelly sizing + paper trading begins | 30 days paper; reconciliation drift <1bp |
| **4** | Month 4 | Risk gate + kill switch + observability | Chaos test passed; alpha-decay dashboard live |
| **5** | Month 5 | Live execution at 0.1× normal size | 30 days live; zero unreconciled positions; zero double-fires |
| **6** | Month 6 | Scale to 1× if KPIs met, OR pivot to single-name OR research-tool monetization | Decision: live trading vs SaaS vs research |

---

## The Decision Gates (be ruthless)

**At end of Month 2:** if walk-forward Sharpe < 1.0 across the test windows, the swarm has no edge on SPX.
- Pivot to single-name 0DTE (NVDA/TSLA/AAPL) and re-run the playbook
- OR pivot to monetizing the framework as a research tool / SaaS
- Do NOT proceed to live execution

**At end of Month 5:** if 30-day paper P&L (after slippage) < SPY return for the same window, the system is paper-edge but not real-edge.
- Do NOT fund with real money
- Continue paper trading until 90 days of positive expectancy show up

**At end of Month 6:** if 30 days of 0.1× live execution shows positive expectancy after all costs, scale to 1×. If not, accept the result and either iterate or shutdown.

---

## What "Hedge Funds Haven't Seen" Could Honestly Mean

The biggest fund advantage on SPX 0DTE is **execution latency** (microsecond) and **inventory** (they're MMs, not directional bettors). A retail trader can't replicate either. But there are three things hedge funds genuinely *can't* do that you can:

1. **Capacity-arb** — strategies that work at $25k-$250k and die at $25M. The pin/MOC/vol-event plays in the Market Maker brief are this category.
2. **Adversarial swarm reasoning** — funds optimize for IR. They will never run a 24-agent debate that takes 90 seconds. They optimize for sub-100ms decisions. Your slow, deliberative, multi-perspective reasoning *is* the moat for trades that mature over hours, not microseconds.
3. **Public credibility moat** — build SwarmSPX in public on X. Every trade public, every loss public, every backtest reproducible. After 12 months of audited public track record, you have something Citadel can never have: trust from retail. Monetize at that point, not before.

---

## The Honest Final Take

You have ~$25k of risk capital and 6 months of time. Three honest paths:

**Path A — Trader (hard mode).** Do the 6-month plan. At Month 2 decide if you have edge. If not, accept it. If yes, scale carefully. **80% probability of ending year flat to mildly positive, 15% probability of meaningful gains, 5% probability of ruin.**

**Path B — Tool builder (medium mode).** Build SwarmSPX as a public research tool / SaaS. Charge $99/mo for the dashboard + signals + audit. Don't trade it yourself with real money. **The 24-agent debate dashboard is more interesting than 95% of paid trading tools on the market. This is your most likely path to sustainable income from this work.**

**Path C — Hybrid (recommended).** Build for Path B publicly. Trade it privately at small size. Use Path A's discipline. Use Path B's revenue to fund the data subscriptions, the VPS, the next 6 months of building. The dashboard subscribers ARE your alpha decay alarm — when they stop renewing, your edge is gone.

**Recommended: Path C.** You already have the engineering to monetize the platform. Use the trading P&L as the "audit trail" that gives the SaaS credibility. Don't bet the rent on edge you haven't proven yet.

---

*Specialist briefs:*
- `01-quant.md` — Quant (Renaissance-school)
- `02-marketmaker.md` — Market Maker (Citadel-school)
- `03-ml.md` — ML researcher (DeepMind-school)
- `04-architect.md` — Systems architect
- `05-risk.md` — Risk + behavioral (Taleb-school)
- `06-heretic.md` — Contrarian / lateral
- `07-data.md` — Alt-data lead (Point72-school)
