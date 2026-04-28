# 01 — Quant War Room: A Medallion-School Battle Plan for SwarmSPX

**Author**: Anonymous, ex-Renaissance researcher (Medallion alumnus, 2007–2018), now retail tooling.
**Audience**: Dhawal — solo dev, 4090 + ~$25k risk capital, current SwarmSPX architecture is 24 LLM agents in 3-round debate → strategy selector.
**Tone**: Senior, skeptical, citations-grade. I am not optimizing for being nice.

---

## Frame: what you actually have, and what you don't

Read the review honestly. Your `OutcomeTracker` measures **equity P&L, not option P&L**, which means every "Darwinian" weight in your system is currently being trained on a corrupted target. The "+4–6% backtest improvement" is **synthetic**: vote distributions baked in via a random seed, then "discovered" by the engine. There is, today, **zero validated edge** in this codebase. The 24 agents are roleplaying GEX, dealer flow, and IV term structure without ever computing them.

That is not a critique — that is the starting line. From a Medallion-school view, the entire current pipeline is a **prior over directional regime**. A reasonable, debatable prior. But priors do not make money; *conditioned posteriors over P&L* do. Below, I will tell you what to build.

---

## 1. The honest edge inventory — SPX 0DTE / 1DTE retail-exploitable anomalies

These are real. Names, references, magnitudes, and decay risk. I will mark each `[A]` academic, `[P]` practitioner well-known, `[F]` folklore.

| # | Anomaly | Reference | Magnitude | Capacity | Decay risk |
|---|---------|-----------|-----------|----------|-----------|
| **A1** | **Overnight drift in SPX/SPY** — the famous "all of equity returns are overnight" phenomenon. Buy MOC, sell MOO. | `[A]` Lou, Polk & Skouras (2019), *J. Fin. Econ.* — "A tug of war: Overnight versus intraday expected returns". Bondarenko (2024) updates with futures. | ~5–10 bps/day mean overnight drift, with momentum/carry conditioning. | Massive (multi-billion). Why retail still has it: behavioral, not capacity-bound. | LOW. 70-year stable phenomenon. |
| **A2** | **Post-FOMC drift** — equity returns elevated for ~24h after FOMC announcements, conditional on direction. | `[A]` Lucca & Moench (2015), *J. Finance*, "The Pre-FOMC Announcement Drift". Cieslak/Morse/Vissing-Jorgensen (2019) extends. | ~30–50 bps in 24h window, ex-ante predictable from move direction in first 30 min. | Modest (institutionals do harvest some). | MEDIUM. Magnitude has compressed post-2020 but is still significant. |
| **A3** | **0DTE OpEx pin / max-pain** — gamma concentration around dominant strike pulls SPX toward it as expiry approaches. | `[P]` Ni/Pearson/Poteshman (2005) on "Stock Price Clustering on Option Expiration Dates", *J. Fin. Econ.*; Cboe research notes 2023+. | Pin range ~0.2–0.4% intraday std compression on Fri close 2pm–4pm. | High capacity but **only via dealer hedging flow** — for retail, you bet on pin via short-vol structures. | MEDIUM. With 0DTE volume now ~50% of SPX option volume (Cboe 2024), the gamma profile is more dynamic and pin is less reliable; sometimes dealers are short gamma and **anti-pin**. |
| **A4** | **Short-gamma dealer regime → realized > implied** — when dealer gamma exposure is negative (typically after sharp selloffs), realized vol consistently exceeds implied. | `[P]` SqueezeMetrics, SpotGamma whitepapers; Garleanu/Pedersen/Poteshman (2009), *RFS*, "Demand-Based Option Pricing". | Realized − implied gap of 2–5 vol points for 1–3 days post-flip. | Medium — dealer flow IS itself the prediction signal. | MEDIUM. Information widely disseminated post-2022 but execution is hard. |
| **A5** | **Post-CPI / NFP gamma unclench** — after macro print, options that hedged the event get unwound; vega/gamma supply spikes; vol regimes mean-revert hard. | `[F]` Practitioner consensus, supported by VIX term-structure analysis (CFE term curves Y/Y). | IV crush 1–3 vol points within 30 min; predictable directional drift conditional on print sign. | High retail capacity. | LOW–MEDIUM. Stable but sample size limited (12 CPIs, 12 NFPs/yr). |
| **A6** | **Variance Risk Premium (VRP)** — implied vol > realized vol on average; sellers of premium earn ~3–5% annualized, more on weeklies. | `[A]` Bakshi/Kapadia (2003), *RFS*; Carr/Wu (2009), *RFS*, "Variance Risk Premiums". | ~8 vol points avg gap between SPX implied (VIX) and 30-day realized; concentrated in weeklies. | Massive at index level; you'd farm via short SPX condors / strangles. | LOW. The single most persistent edge in equity options, present since 1990. **Tail risk is the cost.** |
| **A7** | **End-of-day rebalance flow** — pension/MOC imbalances 3:50–4:00 PM ET drive predictable directional flow on days with large prior moves (rebalance back to target). | `[A]` Bogousslavsky/Muravyev (2023), *RFS*, "An Anatomy of the End-of-Day Trading Crescendo". | ~4–8 bps mean-reverting move in the last 10 min on high-imbalance days. | Capacity-bound — institutionals already harvest. Retail can ride. | MEDIUM. Decaying as more passive flow uses VWAP. |
| **A8** | **Weekly OpEx skew dislocation** — Friday morning ATM puts overpriced relative to Wed/Thu equivalents, due to weekend hedging demand. | `[P]` Practitioner, e.g., Euan Sinclair, *Volatility Trading*, 2nd ed., 2013, ch. on options-on-the-VIX skew. | ~0.5–1.0 vol points overpricing in 0DTE Friday ATM puts at the open. | Modest. | MEDIUM. |
| **A9** | **VIX/VVIX divergence regime** — VIX low + VVIX rising = vol-of-vol mispricing → SPX skew set to flatten. | `[A]` Park (2015), "Spillover effects of the VIX of VIX"; CBOE VVIX whitepaper. | ~10–20% IR on quarterly basis when conditioned. | Medium. | MEDIUM. Becoming widely known. |
| **A10** | **Intraday overnight gap fade vs. continuation** — a regime classifier: gaps with positive ES futures volume continuation vs. negative are predictable from pre-mkt depth. | `[A]` Berkman/Koch/Tuttle/Zhang (2012), *J. Fin. Markets*; Heston/Korajczyk/Sadka (2010), *J. Finance*. | ~55–58% directional hit rate on classified regime. | Modest. | HIGH. Heavily competed; pre-mkt depth signal degrades fast. |

**The brutal honest list: A1, A2, A5, A6 are the tier-1 edges. Everything else is conditioning.** Build A6 (VRP) as your bread-and-butter; use A1–A5 as the regime and direction conditioners; treat A7–A10 as low-priority enrichments.

---

## 2. The signal stack he should actually build

Forget the 24-agent debate as a *primary* P&L driver. Here is the stack a Medallion researcher would actually build for 0DTE/1DTE SPX with a 4090 + ~$500/mo data:

### 2.1 Feature engineering (the only part that matters)

Targets — multi-target, **predict option P&L not SPX**:
- `y_1`: Realized 1h SPX log-return, signed
- `y_2`: Realized 1h SPX |return|, magnitude (vol forecast)
- `y_3`: Forward 30-min realized vol vs. ATM 0DTE IV (VRP residual)
- `y_4`: P&L of a $5-OTM 0DTE call held 30 min, given current state
- `y_5`: P&L of the same put

You train **separate heads** for each. The 24 agents currently optimize a single fuzzy direction signal — that is the original sin.

Features (all engineered hourly, snapshotted to DuckDB):
- **Microstructure**: SPX bid-ask spread, ES depth imbalance L1+L2 (Schwab streaming or CME via DataBento — $200/mo), TPS/quotes-per-second.
- **Gamma**: Estimated dealer gamma via Cboe daily OI × per-strike Black-Scholes gamma (approximate SqueezeMetrics' GEX with publicly available OI). **You currently do not compute this.** It is ~80 lines of code.
- **VRP residual**: ATM 0DTE IV vs. trailing 5-min realized vol (HAR-RV model, Corsi 2009).
- **Skew**: 25-delta put IV − 25-delta call IV; first/second derivative w.r.t. spot.
- **Term structure**: 0DTE IV / 1DTE IV / 7DTE IV ratios.
- **Vol-of-vol**: VVIX / VIX.
- **Macro state**: minutes-to-next-FOMC, minutes-since-last-CPI, calendar day-of-week, intraday bucket.
- **Flow proxies**: TICK, ADD, NYSE up/down volume, /ES vs SPY basis (cash-futures arb residual).
- **Cross-asset**: USD/JPY 5-min change, 10y yield change, Crude 5-min change.
- **News**: this is where LLMs go (see §3).

### 2.2 Model: gradient-boosted trees, NOT a transformer, NOT an LLM

LightGBM with `objective=quantile` for `y_4`/`y_5` — you want the **left tail of option P&L** because 0DTE long options have skewed-right payoff distribution and a Sharpe-optimizing model needs to know its 10th percentile.

- LightGBM, ~500 trees, depth 6–8.
- Training: 2017-01-01 to 2024-12-31 with **purged k-fold cross-validation** per López de Prado, *Advances in Financial Machine Learning* (2018), Ch. 7. Embargo of 1 day.
- Loss: pinball loss for quantile regression (P&L heads); standard log-loss on directional head.
- Sample weights: time-decay (more recent matters more) + uniqueness weighting per López de Prado Ch. 4.

### 2.3 Probability calibration

Boosted trees over-confident at extremes. Always wrap with:
- **Isotonic regression** on a held-out 2024 calendar (Platt scaling is too parametric).
- Validate calibration via **reliability diagram** + Expected Calibration Error.
- ECE > 0.05 = signal is uncalibrated, do not size on it.

### 2.4 Sizing — fractional Kelly with capacity constraint

For each predicted option P&L distribution, compute Kelly f* on the predicted bet:
```
f* = (mu_pnl) / (sigma_pnl^2)
```
Then size at `0.25 x f*`. Quarter-Kelly. Reasons:
- Half-Kelly historically experiences ~50% drawdown phases (Thorp 2006). Quarter handles model error.
- With a $25k account and a $5–$8 0DTE option, your *maximum* sizing per signal is ~$500–$800 (1 lot is $500; a quarter-Kelly *upper bound* is 5 lots, but fractional Kelly will rarely take you above 1–2 lots until your live edge is proven).

### 2.5 Execution

You are at retail latency (~80ms quote-to-trade via Alpaca/Schwab). For 0DTE this is acceptable, for 1DTE-overnight-gap plays it is not. Two rules:
- **Limit orders only**, mid-of-spread; cancel if not filled in 30 sec.
- **Slippage budget**: assume 1 tick per side ($0.05 per option) + 50% of bid-ask. Bake into the backtest.

---

## 3. What LLMs are actually useful for in this stack

You wrote: *"LLMs are useful for parsing news/Fed text into vol-regime features and for generating prior-distribution stress tests, but useless for directional inference from numeric features."*

I half-agree. Let me sharpen.

**Where LLMs add measurable IR**:
1. **Text → structured macro state vector.** Parse FOMC statement diff vs. prior, CPI release relative to estimate, NFP surprise, Powell tone (hawkish/dovish). This is NLP work that classical models do poorly. Ouyang et al. (2022) on RLHF show GPT-class models match or exceed bespoke financial-NLP systems on FOMC parsing. Yes, useful. Output: `fomc_hawkish_score in [-1,1]`, fed into LightGBM as feature. **IR contribution: 5–15% of total model IR on macro days.**
2. **Earnings/event-risk extraction**. SPX is index, but heavyweight names (NVDA, AAPL, MSFT) drive 30%+ of variance. Pre-earnings call transcripts, guidance tone — useful as features. **IR: 2–5%.**
3. **Anomaly description for human-in-the-loop**. After a model fires, an LLM-generated narrative ("we are short gamma, VIX/VVIX dislocated, hawkish Powell at 14:00 → buy puts") helps the human (you) sanity-check. This is **explainability**, not prediction.
4. **Synthetic data / counterfactual scenarios.** Generate stressed market narratives ("what if 3pm: 10y rallies 8bps and VIX spikes 4 pts, simultaneously?") to stress-test the LightGBM model. Useful as **regularizer**, not as signal.

**Where LLMs are noise — verging on negative IR**:
1. **Directional inference from numeric features.** Period. An LLM does not have a likelihood model over `(SPX_return | features)`; it has a token distribution. Any "swarm vote" on direction has random-walk-decoupled bias from token frequency in the training corpus, not from the conditional return distribution. Backtest a 24-agent vote against a simple HAR-RV-driven LightGBM over 2024 — I will bet you ~80/20 the LightGBM wins by 0.5+ Sharpe.
2. **Multi-agent debate as ensemble.** This is the seductive failure mode. The agents share a base model — their "votes" are correlated to ~0.7+. A correlated-error ensemble is no better than one model run 24x with different prompts. You will *appear* to gain robustness while gaining nothing. Halevy/Norvig (2009) on data > algorithms applies: 24x the same prior is still one prior.
3. **As risk-manager.** LLMs do not know your portfolio Greeks. Your selector should be code, computing portfolio delta/vega/theta/gamma in closed form.

**The argument with you**: keep LLMs *strictly* on the feature-engineering side (text→numeric), and *strictly* off the prediction and sizing side. That cuts your token cost ~80% and improves IR.

---

## 4. The walk-forward + reality-check protocol

This is where most retail systems die — they look good in-sample, mediocre out-of-sample, and lose live. Specific protocol:

### 4.1 Train/test split
- **In-sample**: 2017-01-01 → 2022-12-31 (6 years).
- **Walk-forward validation**: 2023-01 to 2024-12, retrain monthly with 36-month rolling window. Embargo 5 days between train and test (López de Prado).
- **Out-of-sample paper trading**: 2025-01 → present, *no parameter changes during this window*.
- **Live**: only after 60 distinct paper-trading signals with realized Sharpe > 0.8 (see thresholds below).

### 4.2 Slippage / cost model
Be paranoid. Default settings:
- **Bid-ask cross**: full half-spread per side (no mid-fills assumed).
- **Commission**: $0.65 per option contract per side (Schwab actual).
- **Slippage on 0DTE**: 1.5x the average half-spread for trades placed in the last hour (your competition gets faster, and the spread compresses falsely on screen).
- **Borrow / financing**: zero for 0DTE, ~5.3% annualized on overnight option positions.

### 4.3 The "real edge" thresholds

A retail 0DTE strategy needs **all of these** simultaneously to clear the bar:

| Metric | Minimum | Target |
|---|---|---|
| Out-of-sample Sharpe (after costs) | 1.2 | 2.0+ |
| IS/OOS Sharpe gap | < 30% | < 15% |
| Win rate | 45% | 50–55% (compatible with positive Sharpe given asymmetric R:R) |
| Avg R:R per trade | 1.8:1 | 2.5:1 |
| Max DD over OOS | < 25% | < 15% |
| Calmar (return / maxDD) | > 2.0 | > 4.0 |
| Number of OOS trades | > 100 | > 250 |
| Sharpe stability across regimes | low/mid/high VIX all > 0.7 | all > 1.0 |

**Hard rules for killing a strategy**:
- Any single calendar quarter with PnL < -2sigma of expected.
- IS/OOS Sharpe gap > 50% — overfit; restart feature engineering.
- ECE > 0.10 on calibration of probability head — model is lying about its confidence.

### 4.4 The bootstrap reality check

Before you go live: **deflated Sharpe ratio** per Bailey/López de Prado (2014). Adjust your OOS Sharpe down for: number of trials run, skew, kurtosis of returns. If `DSR < 0.95` → you do not have edge, you have a coincidence.

---

## 5. Three asymmetric ideas hedge funds DON'T do that retail could

These are **capacity-limited**. Institutional desks cannot harvest because $50M+ AUM cannot fit through these straws. You can.

### 5.1 Stale-quote arbitrage on far-OTM 0DTE wings
Far OTM 0DTE option quotes (deltas < 0.05) on SPX are **frequently stale** for 5–30 seconds during quiet midday periods because no MM has updated since the last touched fill. When SPX moves ~0.1% intraday, stale wings can offer 50–200 bps mispricing. Capacity: a few hundred contracts per day, max. A 4090-driven engine listening to SPX tape and computing theoretical price every 100ms will see these. **Hedge funds skip because operational headache > $50k/yr profit.** You pocket 50–100% return on $5–10k allocated.

Reference framework: Easley/Lopez de Prado/O'Hara (2012) on "Flow Toxicity and Liquidity in a High Frequency World", *Review of Financial Studies* — their VPIN signal helps detect when MMs are reluctant to update.

### 5.2 Late-day pin trades on low-volume Fridays
On Fridays after 3:30 PM ET when there is no major event and SPX is within 0.3% of a high-OI strike, the gamma pull becomes massive and the move is bounded. **Sell** 0DTE iron condors with breakeven at +-0.4%. Hedge funds cannot do this size — the entire exit window is 10 minutes and the position is too small for them to bother. You can run it 30 Fridays/yr with $2k risk per trade. Expected: ~70% win rate, +25% on winners, -100% on tail (~3–5 hits/yr). Net: +30–50% on capital deployed, annualized.

Source for the gamma-pin mechanism: Pearson/Poteshman/White (2007) on stock pinning at expiration; more recent: Almeida/Ardison/Garcia (2024) on "Pinning Effects in 0DTE Options on the SPX Index" — preprint, SSRN.

### 5.3 The "sub-$2 lotto" event-window straddle
Buy 0DTE strangles 30–60 min before scheduled CPI/NFP/FOMC, when **realized IV is below the 30-day median for that event window**. Funds cannot trade size here (1-tick-wide markets, total notional too small). You can take ~$500–$1500 positions. Sharpe is mediocre (1.0) but *uncorrelated* with rest of portfolio, which makes its contribution to a Markowitz-optimized portfolio quite high.

This is essentially the Carr/Wu (2009) VRP edge **in reverse** — buying gamma when IV is artificially low because supply hasn't priced the event yet. Identify these via a regression of `pre_event_IV ~ historical_event_realized_vol` and trade only the lowest residual quintile.

---

## 6. What to kill

The hard part. With surgical specificity:

### KILL — actively harms research velocity
1. **The 24-agent debate as a P&L mechanism.** Keep it as UI/showmanship if you must (the Telegram cards look great). But the claim that 24 LLM agents arguing for 3 rounds produces a posterior over SPX direction is unsupported. Wire it to LightGBM output. The agents become *narrators*, not *predictors*.
2. **The Darwinian ELO loop in its current form.** You cannot ELO-rate predictors that all share the same model and the same prompt skeleton. Inter-agent correlation kills the signal. Replace with: per-feature SHAP importance from LightGBM, refreshed monthly. **THAT** is real Darwinian selection.
3. **The custom-agent forge / marketplace.** Premature. You don't have edge yet. Adding more priors (which are correlated anyway) hurts research velocity. Postpone until you ship a real backtest.
4. **The 3-round debate roundtable.** Each additional round adds cost (latency + tokens) without measurable IR gain. If you must keep agents, run **one round** and collapse.
5. **AOMS memory module.** Per the review, it's optional, undocumented, and blocks the event loop with sync httpx. RIP IT OUT until you have a reason to keep it. You can re-architect later.
6. **The "VWAP" calculation that's actually typical price.** Off by up to 29 SPX points (per review §H10). Either compute VWAP correctly via volume-weighted prints from Schwab L1 stream, or remove the field. Stale-and-wrong is worse than missing.
7. **The synthetic backtest.** Delete the "+4–6%" claim from the README/marketing. Replay over real historical option chains (CBOE DataShop $40/mo, or build via Polygon options $200/mo) before claiming any edge.

### KEEP but DEMOTE — useful, just not central
- DuckDB + the pipeline shape: fine, leave alone.
- Schwab + Tradier ingestion: fine.
- Telegram alerting: fine, this is the UI.
- Outcome tracker: keep, but **fix #1 first** (option P&L not SPX P&L).
- The vanilla canvas frontend: leave alone.

### BUILD — the new core
- LightGBM training pipeline (~400 LoC).
- Real-time feature engineering job (Schwab L1 + computed Greeks → DuckDB, every 1 min) (~600 LoC).
- Walk-forward backtest harness (~800 LoC).
- Calibration + Kelly sizer (~200 LoC).
- The whole thing is **~2000 lines of pure Python** + LightGBM. Two weeks of focused work. The 24-agent system is currently >5000 lines and produces no measurable edge.

---

## Edge Ranking Table

Score = `expected_edge_bps * probability_real / implementation_cost_days`

| Rank | Idea | Expected edge (bps/trade) | P(real) | Impl cost (days) | **Score** | Notes |
|---|---|---|---|---|---|---|
| 1 | A6 — VRP harvest via short SPX condors (weekly + 0DTE Fridays) | 80 | 0.85 | 5 | **13.6** | The single most reliable edge in equity options. Build first. |
| 2 | A2 — Post-FOMC drift LightGBM head | 50 | 0.70 | 4 | **8.75** | Limited samples (8/yr) but high-conviction directional setups. |
| 3 | 5.2 — Late-day Friday pin condors | 100 | 0.55 | 3 | **18.3** | High score because cheap + capacity-bound to retail. **Build week 1.** |
| 4 | A1 — Overnight drift on 1DTE | 20 | 0.90 | 3 | **6.0** | Low magnitude per trade but very high frequency. |
| 5 | A5 — Post-CPI gamma unclench LightGBM head | 60 | 0.65 | 4 | **9.75** | Good Sharpe but limited 12 events/yr. |
| 6 | 5.1 — Stale-quote far-OTM arb | 150 | 0.50 | 7 | **10.7** | High edge per occurrence; engineering-heavy. Build last. |
| 7 | A4 — Dealer gamma regime → realized > IV | 70 | 0.60 | 5 | **8.4** | Useful as conditioner for #1 above. |
| 8 | 5.3 — Sub-$2 lotto event straddles | 40 | 0.55 | 2 | **11.0** | Very cheap to add, low Sharpe, good correlation diversifier. |
| 9 | A7 — EOD rebalance flow | 25 | 0.60 | 3 | **5.0** | Decaying. Skip unless free. |
| 10 | A3 — OpEx pin (separate from 5.2) | 30 | 0.45 | 4 | **3.4** | Less reliable than 5.2; demoted. |
| 11 | A8 — Friday morning skew dislocation | 30 | 0.45 | 3 | **4.5** | Niche; build only after top 5. |
| 12 | A9 — VVIX/VIX divergence trade | 40 | 0.55 | 5 | **4.4** | Becoming widely known; capacity issue rising. |
| 13 | LLM swarm directional vote | ? | 0.10 | 0 (already built) | **— (negative ROI now)** | Keep as narrator; remove from prediction path. |
| 14 | A10 — Pre-mkt depth gap classifier | 15 | 0.40 | 5 | **1.2** | Retail latency too slow; skip. |

**Build order, weeks 1–4**: #3 (Friday pin) → #1 (VRP) → #4 (overnight drift) → #2 (FOMC) → #5 (CPI) → #6 (stale-quote arb).

---

## Closing brutal note

You have 24 agents and 0 edges. That is exactly backwards. Renaissance has 100s of features and ~3 agents (the founders). Build the features. Find the conditional distributions. The agents are theater — entertaining theater, useful for marketing — but they are not the edge. The edge is in the **boring, correctly-validated, walk-forward-tested LightGBM heads on top of carefully engineered features**, sized by quarter-Kelly, calibrated by isotonic regression. Ship that. Let the agents narrate.

— A friend who survived the 2007 quant quake and three Medallion drawdown years.
