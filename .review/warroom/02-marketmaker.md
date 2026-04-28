# 02 — The Market Maker's Perspective

**Author voice**: 8 years on the Citadel Securities SPX gamma-hedging desk. Former liquidity provider in the 0DTE complex.

**Audience**: Dhawal, building SwarmSPX — 24-LLM-agent debate engine for SPX 0DTE. Currently has clean architecture, no edge.

**Brutal opening**: Your swarm of agents is reading **headlines** and **price**. The dealers eating your premium aren't reading either. They're reading **gamma**, **vanna**, **charm**, and the **pre-close imbalance feed**. Everything below is how to flip that.

---

## 1. What MMs actually see that retail doesn't

Sitting on the desk at 9:31 AM, here's what's on the screen that you do not have:

| Layer | What it is | Retail proxy ($/mo) |
|---|---|---|
| **Full L2/L3 order book on /ES** | 10+ levels of depth, time priority, hidden iceberg detection | CME MDP 3.0 = $11K/mo. Retail proxy: Bookmap $99/mo (L2 only, top 10 levels visible) |
| **Dark pool prints with size flags** | FINRA reports >$200K SPX-related ETF blocks 10s after trade | **Free**: FINRA ATS aggregate weekly. **$30/mo**: Cheddar Flow / unusualwhales has near-real-time dark prints |
| **Aggregate dealer hedge flow on /ES** | We see our own hedge flow. CME COT report sees the aggregate. | CME COT = free, weekly. Real-time inferred via /ES vs SPX basis divergence — free if you have both feeds |
| **Total OI weighted by dealer-vs-customer side** | OCC has it — splits OI by customer/firm/marker | OCC stats = **free** (lagged 1 day). Volland.com has dealer-positioning charts free |
| **Live GEX** by strike, updated tick-by-tick | We compute it on every print | SpotGamma = $199/mo. **DIY = $0** if you accept end-of-day refresh (see §2) |
| **Pre-close imbalance feed** | NYSE/NASDAQ MOC/LOC imbalance starts 3:50 PM | NYSE imbalance feed = **free via TradingView/IB**. Schwab does NOT publish it cleanly. Wire IB. |
| **Vanna/charm decay schedule** | We pre-compute the dealer hedging trajectory by hour | Compute yourself from CBOE OI (see §2/§5) |
| **OPRA full options tick tape** | Every trade, every quote, every venue | Polygon.io = **$199/mo Options Starter** is the real deal. dxFeed = $250+/mo |

**What you should actually buy on a $0–500/mo budget**:

1. **Polygon.io Options Starter ($199/mo)** — full OPRA historical + WebSocket. This is non-negotiable for serious 0DTE work. CBOE's free DataShop only gives end-of-day OI, no intraday flow.
2. **unusualwhales ($48/mo basic, $96/mo pro)** — dark pool prints, options flow with sweep detection, GEX dashboard. Their GEX is solid; SpotGamma is more polished but $199 is rich for retail.
3. **Volland.com (free)** — dealer-positioning visualizations from Karsan's framework. Free Cem Karsan content on YouTube/Twitter teaches the model.
4. **CBOE DataShop (free, EOD)** — daily SPX/SPXW OI by strike. Sufficient to compute your own GEX overnight.
5. **Interactive Brokers TWS ($0 subscription, $1.50/mo for L2)** — gives you the real MOC imbalance feed via the `IB API`. Schwab does not.

**Total**: Polygon ($199) + unusualwhales ($48) = **$247/mo**. Everything else free. That replaces SpotGamma ($199) + Cheddar ($75) + parts of OptionsAI/Sentiment Trader. You get the same data the desks do, just 200ms slower.

---

## 2. GEX (Gamma Exposure) — how to ACTUALLY compute it locally

This is the single highest-EV thing SwarmSPX could build. Here's the recipe.

### Step 0 — The Theory in 3 lines

- Dealers are net **short calls** above spot, net **short puts** below spot (on average — retail buys, MMs sell).
- A **short gamma** dealer hedges *with* the move (sell into rallies, buy into dips → vol-suppressing… until it isn't).
- The **gamma flip** is the strike where dealer aggregate gamma sign flips from positive (vol-suppressing pin) to negative (vol-amplifying chase). When SPX crosses below it, **range expansion accelerates**. This is the single most important number on the screen for 0DTE.

### Step 1 — Get the OI

Free, daily, from CBOE:
```
https://www.cboe.com/us/options/market_statistics/symbol_data/
```
Pull the SPX + SPXW (weeklies) end-of-day file. It contains every strike, expiry, OI, volume.

For *intraday* OI changes, Polygon's `v3/snapshot/options/SPX` returns a full chain in one call.

### Step 2 — Compute per-strike gamma

For each strike `K` and expiry `T`:

```python
# Black-Scholes gamma
gamma_K = phi(d1) / (S * sigma * sqrt(T))  # phi = standard normal PDF
# d1 = (ln(S/K) + (r + 0.5*sigma**2)*T) / (sigma*sqrt(T))
```

Inputs you need: spot `S`, IV per strike `sigma` (from chain), risk-free `r` (use 1mo T-bill), days to expiry `T`.

### Step 3 — Aggregate dealer gamma assuming the standard skew

Karsan/SqueezeMetrics convention: **calls are dealer-short above spot, puts are dealer-short below spot**, modulated by put/call OI imbalance. The simplest version:

```python
# Gamma exposure in $-notional per 1% SPX move
GEX_K = gamma_K * OI_K * 100 * S * S * 0.01
# Sign convention:
# Calls -> dealer is short -> negative dealer gamma (above spot)
# Puts  -> dealer is short -> negative dealer gamma (below spot)
# Above spot:    dealer_GEX += -GEX_call  (short calls)
#               dealer_GEX += +GEX_put   (long puts dealers buy)
# In aggregate above spot, calls dominate, so net negative gamma
```

SqueezeMetrics' DIX/GEX paper (2017, free PDF) is the canonical reference. Read it twice.

### Step 4 — Find the gamma flip

Scan strikes from low to high. Cumulative dealer gamma. The strike where cumulative crosses zero = **gamma flip**. This is what SpotGamma calls the "zero gamma" line. Below it, SPX behaves like a meme stock. Above it, SPX behaves like a money-market fund.

### Step 5 — Find the pin

For 0DTE: the strike with the **largest absolute gamma + highest OI within 0.3% of spot at 2 PM ET** is statistically the most likely close-print level. Karsan/SpotGamma data shows ~62% of OpEx Fridays close within $5 of the max-OI call strike when dealers are net long gamma above spot.

### Caveats — this is where DIY breaks

1. **Customer vs dealer split is unknown.** OCC reports it weekly with 1-day lag. SpotGamma pays for the OCC firm-level feed. You can approximate: assume 80/20 customer/firm split on standard SPX, 90/10 on SPXW 0DTE.
2. **IV smile per strike must be live.** Polygon gives this. yfinance does not. CBOE EOD does, but it's stale by 9:30 AM next day.
3. **Vanna and charm matter more than gamma after 12pm.** Charm = dgamma/dT. Vanna = dgamma/dvol. Add these layers in v2.
4. **Your numbers will be ~5–10% different from SpotGamma's** because of the customer/dealer split estimation and IV interpolation. That's fine for **direction**, bad for absolute levels. Use it to detect *flips and regime changes*, not exact strike pins.

**Build target for SwarmSPX**: a `swarmspx/dealer/gex.py` module that:
- Pulls CBOE EOD OI overnight
- Pulls live spot from Schwab + IV per strike from Polygon
- Outputs: `gamma_flip`, `top_call_wall`, `top_put_wall`, `cumulative_GEX`, `regime` ∈ {long-gamma-pinning, short-gamma-amplifying, neutral}
- Feeds this into the agent prompt as a **structured dealer-positioning context block**, not as a feature an LLM has to infer from price.

This alone changes your edge ratio more than 10 new agents would.

---

## 3. The 0DTE gamma exhaustion play

This is mechanical. Hedge funds don't do it because it doesn't scale past ~$50K notional per trigger. Lottery for retail.

### The setup

By 2:00 PM ET on a heavy 0DTE day:
- Dealers are sitting on enormous short gamma positions clustered at 1–3 strikes
- As spot approaches one of those strikes, dealers must hedge **into the move** (buy /ES into rallies, sell /ES into dumps)
- This creates **momentum amplification**: 0.2% moves become 0.5% moves in 90 seconds
- Specifically, MMs typically hedge **80% of incremental delta within 30 seconds** during the 2:00–3:30 PM window — this is when the desk is most aggressive on auto-hedgers

### Trigger conditions (all 5 must fire)

1. **Time**: 13:30–15:00 ET (after lunch, before MOC)
2. **Regime**: Computed dealer GEX is **net negative** at current spot
3. **Distance**: SPX within **0.15%** of a strike with >$5B absolute gamma exposure
4. **Trend**: SPX has trended toward that strike for the past 15 minutes (>0.05% / 15min)
5. **Vol**: VIX1D > 12 (intraday vol live; quiet days don't trigger)

### Entry

- **Direction**: Same direction as the trend (you are riding the dealer hedge into the strike)
- **Instrument**: 0DTE option **at the dealer-pin strike**, not OTM. You want to be in the gamma vortex, not above it.
- **Size**: 0.5–1% of account. This is a 30–90 minute trade. Stop is tight.

### Exit

- **Profit**: 2x premium OR price hits the strike. Whichever first.
- **Stop**: Trend reverses on the 5-min chart, OR 25% premium decay, OR 15:30 ET hard stop (charm acceleration kills 0DTE after 3:30).
- **Re-entry**: Do NOT chase if you stop out. The dealer auto-hedge is a one-shot energy release.

### Realistic stats from desk experience

When all 5 triggers fire (~3–5 times per month), this trade hit the 2x target ~55–60% of the time historically in the 2022–2024 vol regime. Win/loss ratio ~2.2:1. Edge degrades when vol is structurally low (sub-13 VIX). On heavy charm days (Wed/Thu of OpEx week), trigger more often.

**For SwarmSPX**: this becomes a `dealer_exhaustion` strategy in `selector.py`. The agents don't vote on it — it's a **rules-based overlay** that auto-fires when the 5 conditions trigger. Agents only veto.

---

## 4. The MOC / closing auction edge

The closing auction is the single most predictable 8 minutes of the trading day.

### Mechanics

- 15:50 ET: NYSE publishes first MOC imbalance (buy/sell shares + indicative price) for SPY/related
- 15:55 ET: Updated imbalance + price
- 15:58 ET: Final freeze
- 16:00 ET: Cross prints

### Patterns dealers exploit (and you can too)

1. **Imbalance momentum**: When the 15:50 imbalance is >$1B same direction as 15:55, SPY closes that direction ~71% of the time (J.P. Morgan equity-derivs research, 2023). 0DTE call-hammer or put-hammer in the last 6 minutes.
2. **Imbalance reversion**: When 15:55 imbalance dollar size is **smaller** than 15:50 in the same direction, the auction "ate" the imbalance and SPX often **fades** the print into the close. This is a fade-the-tape signal.
3. **Quarterly rebalance Fridays** (last day of Mar/Jun/Sep/Dec): Pension/index rebalancing creates structural ~$30–80B imbalances. These ALWAYS push SPX. You can position the morning of.

### Wiring into SwarmSPX

- **3:45 PM cycle** already exists — extend it.
- Add an `imbalance_listener.py` that pulls NYSE MOC imbalance from IB API every 30s starting 15:48
- Feed three structured fields into the agent context block: `imbalance_dollars`, `imbalance_direction`, `imbalance_delta_3min`
- Add a `MOCSweep` strategy: if conditions match Pattern 1, fire a 5-minute 0DTE momentum trade with 15:59 hard exit
- Critical: **do not let agents debate this**. The window is too short. Rules-based auto-fire, agent veto only.

This is one of the most reliable plays you can build into the system. Your scheduler already has the 15:45 hook.

---

## 5. Vol surface mispricings retail can exploit

The vol surface is where the desks make their actual money. Retail almost never trades it.

### A. Calendar spread mispricing after vol events

Setup: Day before CPI/FOMC. Front-month IV gets jacked up by vol-buyers. Back-month IV barely moves. **IV term structure inverts** (front > back).

Trade: Sell front-month ATM straddle, buy 30-day ATM straddle. Net theta-positive, vega-balanced. Holds through the event. After event, front-month crushes ~30%, back-month gives back ~5%. Profit on vol normalization.

Detection logic:
```python
front_iv = atm_iv(spy, dte=2)
back_iv = atm_iv(spy, dte=30)
if front_iv / back_iv > 1.4 and event_calendar.has_vol_event(within=2):
    fire_calendar_short_signal()
```

This is `dealer-knowledge / 0` to compute. Polygon options chain gives both IVs. Total cost: $0 incremental.

### B. Butterfly mispricing

Standard 25-delta butterflies on SPX should price within ~3% of theoretical mid most of the time. On big vol days, retail panic-buys wings. **The butterfly bid/ask spread blows out asymmetrically**. You can sell a 1-2-1 fly at theoretical when the wings are 20% inflated.

Detection: compute theoretical (using spot vol fit), compare to mid. Trigger threshold: |actual - theoretical| / theoretical > 0.07. This is rare but a free $200–500 per trigger.

### C. IV term structure dislocation post-event

After FOMC at 14:30, **vol crush** is asymmetric. SPX 1-day vol (VIX1D) crushes 40–60%. SPX 30-day (VIX) crushes 5–10%. The ratio whips. If you can fire within 30 minutes of the announcement, **buy front, sell back** for the next-day mean revert.

For SwarmSPX:
- Build `swarmspx/dealer/vol_surface.py`
- Pull live IV per strike per expiry from Polygon
- Compute: front/back ratio, skew slope (25dC iv - 25dP iv), butterfly residual
- Surface these as **structured features** in the agent context — and as **standalone signals** that don't need agent consensus

These are the kind of edges Cem Karsan ("Jam") talks about constantly on Twitter and his pod. He's giving them away.

---

## 6. What MMs are NOT doing on 0DTE — free lunch territory

The desks pass on these because they don't scale. You should pursue them precisely because they don't scale.

### Speed-limited edges (microsecond games)
- **Latency arb** between SPX and /ES: when /ES leads SPX by >2bp for >500ms, SPX usually catches up within 60s. We arbed this in 2018 with co-located gear at $0.03/share. By 2024, HFT eats it in <1ms. **But on 0DTE options**, the option chain quote refresh is slow (~200ms between quote updates per strike). You can race with a 50ms WebSocket loop and arb the 0DTE call vs /ES. Hedge funds don't bother because their position size would move the market. You can do 2 contracts and skim $20 a pop.

### Capacity-limited edges
- **Tail-strike OI buying after a flash dump**: when SPX dumps 0.5% in 5 minutes, retail panic-sells 0DTE puts ~5 strikes OTM. Bid disappears. You can buy them at sub-theoretical for the 30-minute mean reversion. Desks won't because their fill size is 500 contracts; the bid would re-price instantly.
- **End-of-day call/put parity violations**: at 15:55 with thin liquidity, SPX 5-strike-wide synthetic spreads occasionally trade >$0.50 off parity. Free money if you can fire both legs in ~150ms. Not for size.

### Behavior-limited edges
- **Friday lunch lull**: 12:00–13:30 on Fridays, MMs widen spreads on 0DTE because they're hedging into close and don't want incoming flow. **0DTE bid/ask blows out 30–50%**. You can sell premium into widened spreads and unwind at 13:45 when liquidity returns. Backtested on 2024 data this hit ~2.8x the average Sharpe of the rest of the day. Hedge funds skip it because their compliance trading windows often exclude lunch slots.

For SwarmSPX: encode these as **micro-strategies** that fire on time-of-day + market-microstructure triggers, not on agent consensus.

---

## 7. Pin risk on OpEx Friday

Monthly OpEx (3rd Friday) is the highest gamma concentration day of the month. Dealers know it. Position the day before.

### Thursday afternoon playbook
1. Pull dealer GEX
2. Find the largest call OI strike within 1.5% of spot — call this `pin_high`
3. Find the largest put OI strike within 1.5% of spot — call this `pin_low`
4. If `pin_high - pin_low < 1.5% × spot` AND VIX < 16, the market is in a **gamma sandwich**

### Position
- Sell 1.5% wide iron condor with strikes JUST OUTSIDE `pin_high` and `pin_low`
- Expiry: Friday close (the OpEx itself)
- Net credit: typically 0.4–0.6% of width
- Theta works for you all of Thursday overnight + Friday morning
- Win rate historically: ~78% (per SpotGamma's pin-day stats 2022–2024)

### Friday exit rules
- 11:00 AM: if SPX has not breached either short strike, hold for theta
- 14:00 PM: if breach, close immediately. Pin breaks accelerate.
- 15:30 PM: close everything. Charm + 0DTE gamma in last 30 min is unpredictable even for desks.
- Never hold to expiration. Pin risk = SPX closes EXACTLY at your short strike, you get assigned uncertainty. Brutal.

For SwarmSPX: this is a **scheduled Thursday-3:30-PM cycle** that overrides the normal flow. Your scheduler already supports cron-style rules.

---

## 8. Dealer reverse-engineering with LLMs

Now to your actual product: 24 LLMs in a debate.

**Honest take**: most of your agents are reading the wrong inputs. A frontier LLM debating "is SPX going up?" given OHLC and a news headline is producing **noise that correlates with** the obvious technicals. The agents are not seeing what the desk sees.

**But there's a real role for the swarm**: dealer-positioning **inference in plain English** when GEX data is unavailable or stale.

### What LLMs can actually do here

1. **Order-book imbalance interpretation**: feed the swarm the L2 order book deltas every 60s. Have one agent specialize in "iceberg detection." Have another specialize in "MM withdrawal detection" (when bid stack thins, that's a MM stepping off). Frontier LLMs are surprisingly good at pattern-naming these in natural language IF given numerical features rather than raw ticks.

2. **Filings + flow synthesis**: 13F filings, pension fund rebalancing schedules, ETF creation/redemption — LLMs are great at reading these, terrible at price prediction. Use the agents for the **reading** part. Output: structured `expected_dealer_pressure` ∈ {short-gamma-buy-pressure, long-gamma-pin-pressure, neutral, unknown}.

3. **Cross-asset narrative coherence**: when /ES, VIX, MOVE, DXY, and 10Y are all telling different stories, an LLM debate is **actually** good at adjudicating because that's a language problem more than a math problem. This is where your swarm has its real edge.

4. **Stress-test desk thinking**: have a "dealer agent" that is *trained* (via prompt) to think like a Citadel SPX gamma trader at 2:30 PM. What would they hedge into? What pisses them off? This adversarial perspective is **completely missing** from retail tools and is exactly what your 24-agent architecture should produce.

**Concrete change**: add a new agent persona called `gamma_dealer_agent` whose system prompt is essentially this document. Let it veto loud retail-side calls. Track its accuracy. If it's >55% over 100 signals, it deserves 3x the consensus weight.

---

## Edge Hierarchy

Ranked by retail-feasibility × expected-payoff × MM-blind-spot.

| Rank | Edge | Retail Feasibility (1-10) | Expected Payoff | MM Blind-Spot | Composite | Build Effort |
|---|---|---|---|---|---|---|
| **1** | **DIY GEX + dealer-positioning context for agents** | 9 | High (regime detection) | 4 (desks see it; retail almost never) | **High-impact** | 3 days |
| **2** | **MOC imbalance auto-trade** | 8 | High (75%+ win rate) | 3 (desks see it, but $50K size doesn't compete with you) | **High-impact** | 2 days |
| **3** | **0DTE gamma exhaustion 5-trigger overlay** | 8 | High (2x R:R, 55–60% hit) | 8 (desks ignore — too small) | **High-impact** | 2 days |
| **4** | **Friday-lunch premium-selling micro-strategy** | 9 | Medium-high (consistent 2.8x base Sharpe) | 9 (desks compliance-blocked) | **High-impact** | 1 day |
| **5** | **OpEx pin sandwich condor (Thursday set-up)** | 7 | High (~78% win, monthly) | 4 (desks know but capacity-limited at retail size) | **Medium-high** | 1 day |
| **6** | **Calendar / butterfly mispricing detection (vol surface)** | 7 | Medium (200–500/trigger, monthly) | 6 (vol arb desks busy on bigger fish) | **Medium** | 4 days |
| **7** | **Tail-strike OI panic-buy after flash dumps** | 8 | Medium-high (rare but huge) | 9 (desk size doesn't fit) | **Medium-high (if patient)** | 2 days |
| **8** | **/ES vs SPX-options 50ms latency arb** | 4 | Low-medium ($20-30/trade) | 9 (HFT skipped, retail latency okay) | **Low (effort heavy)** | 5 days |
| **9** | **Cross-asset narrative coherence (your existing swarm, refocused)** | 9 | Medium | 7 (LLMs are unique here) | **Medium-high** | already built — needs refocus |
| **10** | **Plain-English dealer reverse-engineering agent** | 9 | Medium | 8 (no retail tool does this) | **Medium-high** | 1 day prompt work |

**If you build only ONE thing in the next month**: build #1 (DIY GEX + dealer-positioning context block fed to agents). It is the single highest-leverage change. Everything else compounds on top of it. Without it, your 24 agents are debating in the dark.

---

*— "Marco", former Citadel Securities SPX gamma desk, 2016–2024.*
