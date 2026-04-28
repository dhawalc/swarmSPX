# 07 — Data Acquisition & Validation Playbook

**Author voice**: ex-Point72 alt-data lead. Six years sourcing, validating, and operationalizing non-traditional data sets. Edge comes from data, not from clever models on commoditized data. The fund that paid me did not pay for cleverness — it paid for unique, point-in-time-correct, reconciled feeds. SwarmSPX today has none of that. Right now you have a 24-agent swarm consuming `yfinance` quotes, Schwab L1, and a Tradier options chain. That is a brain with no eyes. Below is what eyes look like.

---

## 1. The Retail Data Stack for SPX 0DTE — Tiered & Priced

**Free tier — what every serious retail desk should already have wired**

| Source | What it gives you | Notes |
|---|---|---|
| **CBOE** (cboe.com/us/options/market_statistics) | End-of-day OI, P/C ratio (equity, index, total), VIX settlement, SKEW index | CSV downloads. The total/equity P/C divergence is a real signal. |
| **FRED** (fred.stlouisfed.org) | DGS10, DGS2, T10Y2Y, BAMLH0A0HYM2 (HY OAS), DTWEXBGS (DXY broad), VIXCLS, NFCI | Free API, 120 req/min. Wire `fredapi` and pull a daily macro pack. |
| **Treasury Direct** | Auction calendar, results, on-the-run yields | 2y/5y/7y/10y/30y auction tail/non-tail moves SPX intraday. |
| **EDGAR** | 10-K, 10-Q, 8-K, Form 4 (insider), 13F, 13D/G | Real-time filing feed via RSS or `sec-edgar-downloader`. |
| **Federal Reserve speeches** | federalreserve.gov/newsevents/speeches.htm | Scrape, score, alert. Powell speech moves vol; you want LLM scoring within seconds. |
| **CapitolTrades / Quiver free tier** | Congressional trade disclosures (Pelosi, Crenshaw, etc.) | 24h–30d lag, but the tail is exploitable. |
| **NYSE / Nasdaq breadth** | TICK, TRIN, A/D line via free quote API | TICK > +1000 / < -1000 is a real intraday regime signal. |
| **Twitter/X** scraping (Nitter mirrors, snscrape, twscrape) | FinTwit posts | Rate-limited and brittle. Worth $0 only if you accept maintenance overhead. |
| **Reddit** | r/wallstreetbets, r/options, r/thetagang | PRAW + Pushshift archive. WSB ticker/sentiment counts work in regime. |
| **YouTube/podcast transcripts** | yt-dlp + Whisper | Macro voices (Druckenmiller, El-Erian) — score within 60s of upload. |
| **Google Trends** | pytrends | "recession", "spx puts", "vix" search velocity. |
| **CFTC COT** | Weekly Commitments of Traders | Lagged but useful for ES large-spec positioning. |

Set this whole tier up in two weekends. The fund version of this is just FactSet — same data, $50k/seat.

**Cheap tier — $50–500/mo, the actual sweet spot**

| Vendor | Plan | What you get | Annual |
|---|---|---|---|
| **Polygon.io** Options Starter | $29/mo | EOD US options chain, last-quote, 5y history | best $/value in retail |
| **Polygon.io** Options Advanced | $199/mo | Real-time NBBO, full chain, 15y history, options trades stream | the upgrade most retail underestimates |
| **Polygon.io** Stocks Advanced | $199/mo | Real-time L1, L2 (limited), aggregates, news | bundle with options |
| **Tradier Pro** | $10/mo + market data passthrough | Real-time quotes, options chain, low-latency execution | already in your stack |
| **Alpaca** | free / $99 unlimited | Paper + live equities, real-time L1 | you have this wired |
| **NewsAPI.ai (Event Registry)** | $99–$249/mo | 60k+ news sources, semantic clustering, sentiment | better than NewsAPI.org for finance |
| **Marketaux / Finnhub** | $50–$150/mo | Sentiment-tagged company news | you already have a Finnhub key |
| **OpenAI / Anthropic API** | usage | LLM scoring layer | budget $50–200/mo for news+transcript scoring |
| **ScrapingBee / Bright Data** | $49–$249/mo | Captcha-resilient scraping | for CapitolTrades, EDGAR rate-limit bypass, Twitter |
| **AlphaVantage Premium** | $50/mo | Backup macro/intraday | redundancy only |
| **Quandl/Nasdaq Data Link** | $50–$300/mo per dataset | Curated alt-data feeds | one-off datasets |

**Mid tier — $500–2k/mo, where retail starts approaching prop**

| Vendor | Plan | What you get |
|---|---|---|
| **SpotGamma** | $129/mo Standard, $499/mo Pro | Dealer GEX, gamma flip, vanna/charm levels, HIRO, Dark Pool index. The single highest-IR retail subscription for 0DTE. |
| **Unusual Whales** | $48/mo basic, $1,500/mo institutional | Sweep alerts, dark pool prints, Congressional trades real-time, options flow ranked, Reddit/FinTwit aggregator. Their flow ranker is good. |
| **Quiver Quantitative** | $10/mo basic, $100/mo Pro | Congress trades, lobbying spend, Wikipedia views, government contracts |
| **Tickeron / Sentinel / GetVolatility** | $50–$300/mo each | Alternative GEX providers — useful for cross-checking SpotGamma |
| **IBKR Pro** | $10 minimum + market data | NYSE Open/CloseBook adders ~$150/mo; OPRA full at $1.50/exchange | execution + secondary data |
| **Benzinga Pro** | $177/mo | Squawk feed, news with scoring, calendar | the squawk is genuinely fast |
| **The Trade Desk / Convexity Maven** newsletters | $50–500/mo | Curated insight | not data, but flow color |
| **Glassnode** | $39–$799/mo | Crypto on-chain — risk-on/off proxy, exchange flows, stablecoin printing | BTC liquidations lead SPX vol |
| **Dune Analytics** | free tier + $390/mo | SQL on chain data | DIY equivalent of Glassnode |

**High tier — $2k+/mo, where the cost-of-edge curve starts bending**

| Vendor | Plan | What you get |
|---|---|---|
| **Polygon.io Business / Enterprise** | $2k–$10k/mo | OPRA full bundle, all venues, redistribution rights | the closest thing to Bloomberg-lite |
| **CBOE LiveVol Pro / Data Shop** | $2k–$5k/mo | Tick options, complete OPRA, historical depth, GEX/Dealer Imbalance products direct | better than Polygon if you only do options |
| **Cboe Options Hub** | $1k+ | DataShop one-offs, intraday options snapshots | great for backtest |
| **Refinitiv Eikon Workspace** | ~$1.5k/mo | Bloomberg-lite, news, calendars | the LSEG version |
| **FactSet Workstation** | ~$1.8k/mo | Buy-side workstation — flows, holdings, estimates | hedge-fund standard |
| **Bloomberg Terminal** | $2.4k/mo | The thing | bond depth and IB chat are the moats |
| **OptionMetrics Ivy DB** | $5–20k/yr academic, $50k+ commercial | 30y historical implied vol surface | this is the dataset for serious vol research |
| **Tick Data / Algoseek / Dxfeed** | $5k+/yr | Tick history, NBBO reconstructions | for honest backtesting |
| **Dataminr / RavenPack** | $30k+/yr | Real-time news+social signal | not realistic for retail |

The honest answer: above $5k/mo per vendor you are paying for terminal-style entitlements you do not need to trade SPX 0DTE.

---

## 2. The Signals That Actually Predict SPX 0DTE Moves — Ranked

Roughly ranked by historical Information Ratio on intraday SPX moves. IR estimates are from my own work and from public studies (Hull, Carr, Cboe, JPM 0DTE notes 2023–2025). Treat as priors, not gospel.

| Rank | Signal | Bucket | Approx IR | Why it works |
|---|---|---|---|---|
| 1 | **Dealer GEX (gamma exposure) and gamma flip** | Flow | 1.0+ | Dealer-short-gamma → trend day; long-gamma → mean-reversion. SpotGamma productized this. |
| 2 | **VIX term structure (VIX1D / VIX / VIX3M)** | Macro | 0.8–1.0 | VIX1D > VIX = stress at the front, mean-reverting. Cheap to compute, high predictive power. |
| 3 | **0DTE volume share & call/put skew of 0DTE** | Flow | 0.7 | 0DTE is now ~50% of SPX option volume. Imbalance is mechanically directional. |
| 4 | **NYSE TICK extremes** | Microstructure | 0.6–0.8 | TICK > +1000 / < −1000 → exhaustion or breakout regime. |
| 5 | **VVIX / VIX (vol-of-vol)** | Cross-asset | 0.6 | VVIX rising while VIX flat → tail bid building. |
| 6 | **Calendar events (FOMC, CPI, NFP, OpEx, VIX expiry)** | Calendar | 0.6 | Pre-event vol crush, post-event drift. Predictable. |
| 7 | **Sweep alerts above $1M premium** | Flow | 0.5 | Public flow-following has small but real edge in regime. |
| 8 | **Credit spread divergence (HY OAS, IG OAS vs SPX)** | Macro | 0.5 | Credit leads equity at regime turns. |
| 9 | **DXY moves intraday** | Cross-asset | 0.4 | DXY +0.5% intraday is ~−25 bps SPX prior. |
| 10 | **A/D, TRIN, McClellan** | Microstructure | 0.4 | TRIN < 0.5 / > 2.0 are real intraday regimes. |
| 11 | **News velocity (rate of finance-tagged headlines/min)** | Alt | 0.3–0.6 (event-conditional) | The IR is concentrated in tail events. Score this aggressively. |
| 12 | **AAII bull/bear, Fear & Greed, P/C ratio** | Sentiment | 0.3 | Slow but useful as regime filter, not as trigger. |
| 13 | **Crypto BTC/ETH 4h move** | Cross-asset | 0.3 | Risk-on/off leading indicator overnight, fades intraday. |
| 14 | **Sector rotation (XLK vs XLP, XLE vs XLU)** | Cross-asset | 0.3 | Defensive rotation precedes drawdowns. |
| 15 | **WSB / FinTwit sentiment** | Alt | 0.2 | Useful as regime, not signal. Better as contra-indicator at extremes. |
| 16 | **Google Trends spikes** | Alt | 0.2 | Slow. "recession" search velocity worked in 2008/2020/2022. |
| 17 | **Congressional trades** | Alt | 0.1–0.4 (name-conditional) | Pelosi-style names beat market over 1y. Intraday signal? Weak. |
| 18 | **13F lag** | Alt | low intraday, useful for trend | 45-day lag — cohort tilts more than triggers. |

**The takeaway**: GEX + VIX term + 0DTE flow + TICK is a **>1.5 combined IR** stack you can build for ~$130/mo (SpotGamma Standard + free CBOE/FRED + free TICK from any quote vendor). Layer LLM-scored news on top and you have a bona-fide retail edge.

---

## 3. Real Edge Alt-Data Sources Retail Can Actually Access

**Congressional Trade Disclosures.** STOCK Act forces members of Congress to file Periodic Transaction Reports within 30 days. Pelosi-aligned trades have ~6% annualized alpha (Quiver, Unusual Whales studies). Scrape from CapitolTrades.com or buy Quiver feed. Real-time filing detection (via SEC RSS / House Clerk endpoints) gives you a few hours' edge over commercial scrapers.

**SEC 13F.** 45-day reporting lag. Useless as an intraday trigger, but cohort-tilt analysis (e.g. "Citadel raised SPX puts 30%") gives medium-term regime info. Free via EDGAR + `sec-edgar-downloader`. Crowded names + crowded sectors are higher beta during drawdowns — useful priors for the swarm.

**Form 4 Insider Trading.** Filed within 2 business days. Real-time RSS feed. Cluster buying inside SPX components is regime-positive. Build an SPX-component-only Form 4 firehose.

**ETF Flows.** SPY/QQQ/IWM creation/redemption — Bloomberg/Lipper reports daily; ETFDB.com has free dashboards. Massive SPY redemptions = forced equity selling next session. Useful overnight bias signal.

**Crypto on-chain flow.** Stablecoin printing (USDT, USDC), exchange BTC inflows, perp funding rates. Glassnode free tier covers basics; Dune SQL gets you everything. Risk-on/off leading indicator. Liquidation cascades on BTC consistently precede SPX vol expansion in the next 1–2 sessions in the 2022–2025 sample.

**FinTwit follow graphs.** Build the follow graph of @GoldmanSachs, @Citi, @MorganStanley, @jpmorgan, @Fidelity, @BlackRock, plus desk strategists (zerohedge, modestproposal1, etc.). Their tweet velocity and topic distribution shifts before reports. snscrape + an embedding model.

**Federal Reserve speeches.** federalreserve.gov publishes a calendar; speeches drop at scheduled times with PDFs. Score for hawkish/dovish in <5s using Anthropic. Fed speak intraday moves SPX 20–60 bps regularly.

**FOMC minutes / dot-plot diffs.** Diff against prior release. The token-level diff is your alpha.

**Treasury auction tails.** 2y/5y/7y/10y/30y auctions at 1pm ET. A "tail" (auction yield > WI yield) is a buyer-strike signal — equities sell off 20–30 bps within the hour reliably. Treasury Direct publishes results at 1:01pm.

**Job posting velocity.** Indeed/LinkedIn API or Revelio Labs ($1k+) — slow signal, useful for regime.

---

## 4. Data Hygiene Playbook

**Point-in-time correctness.** Most retail backtests cheat by using *current* metadata (sector membership, restated revenue, current OI) on *historical* prices. Build with a `valid_from` / `valid_to` schema for every reference field. For SPX 0DTE specifically: option chain snapshots must be timestamped at the moment they were observable — not reconstructed from EOD.

**Survivorship bias.** Use SPX as written (not SPY constituents — those churn). For agent backtesting on individual names, use CRSP-equivalent dead-name files. Polygon includes delisted tickers.

**Feed latency vs publication latency.** Treasury auction results: published 1:01pm but feed delivery can lag 60–300s on free APIs. Note both `event_time` and `ingest_time`. Your backtest should only see the data at `ingest_time`.

**Holiday + half-day handling.** Use `pandas_market_calendars` (`XNYS` calendar). Hard-coded session windows break on Good Friday, half-days, weather closures, the 9/11 anniversary.

**Restated data.** GDP, NFP, CPI all get revised. Always store the *first-print* value with a `release_id` and only update via a new row, never an in-place edit. ALFRED (FRED's vintage archive) gives you the version history for free.

**Free-API rate limits.** Round-robin keys (FRED, Polygon free, Alpha Vantage), per-key tracker, exponential backoff. Tradier sandbox is rate-throttled differently from production. Schwab caps at 120 req/min — implement a token-bucket. Schwab 401 should trigger one refresh attempt, then fall through to cached data, never an infinite retry loop (see HANDOFF #H7).

**Timezone discipline.** Store everything in UTC, render in ET. The current code's naive `datetime.now()` (CRITICAL #8) is exactly the bug that taints fund-grade backtests too. Use `zoneinfo.ZoneInfo("America/New_York")` and `pandas_market_calendars`. Ban naive datetimes at the type level.

---

## 5. Data Quality Monitoring Layer

Five checks, run every 60 seconds during market hours:

1. **Liveness.** Last quote timestamp delta from now. Alert if >30s during RTH for any feed.
2. **Reasonableness.** SPX move > 2% in one bar → flag for human review. VIX < 8 or > 80 → reject. Option mid > $1000 → reject.
3. **Cross-source reconciliation.** Schwab SPX vs Tradier vs yfinance — alert if any pair diverges > 0.05%. Same for VIX.
4. **OI / volume sanity.** Today's CBOE total volume drop >50% vs trailing-20d → feed corrupt.
5. **NaN / null rate.** % of fields null per feed. Threshold-alert.

Implement as a `DataQualityMonitor` that emits to the existing EventBus. Telegram alert on red. This is also how you catch silent feed degradation (Schwab swapping field names on you, Tradier sandbox returning stale data overnight, etc.).

Reconciliation: keep three sources for SPX, VIX, and the front-month option mid. Use median, not mean — one bad source can't move the median.

---

## 6. News-to-Vol Pipeline — Specific Build

```
[Sources]            [Stream]             [Scoring]               [Action]
NewsAPI.ai      ─┐                      ┌─ Anthropic Haiku ─┐
Polygon news    ─┤                      │  (5s SLA, $0.001)  │
Twitter (X)     ─┼→ Kafka/Redis stream ─┤                    ├→ vol_alert event
Fed RSS         ─┤  (deduplicated by    │  scores:           │   (severity, dir, ttl)
Treasury Direct ─┤   semantic-hash)     │  - novelty (0..1)  │
NYSE / Cboe     ─┘                      │  - finance_score   │   strategy → straddle
                                        │  - direction (-1..1)│  if novelty > 0.7
                                        │  - asset_tags     │   and severity > 0.6
                                        └────────────────────┘
```

**Scoring model.** Haiku 4.5 prompt: "Given headline X, return JSON: {novelty, finance_score, direction, magnitude_bps, decay_seconds}." With prompt caching (Anthropic cache hit ~90%) cost is ~$0.001/headline. Latency P99 < 5s — feasible with Haiku.

**Vol prediction model.** Train on `(news_score → IV change next 60s)` using OptionMetrics or your own Polygon snapshots. Linear or LightGBM. Inputs: novelty, magnitude, time-of-day, current VIX1D regime, dealer GEX state. Output: expected 60s IV move and direction.

**The trade.** If predicted ATM IV move > +5% AND realized vol last 5min < ATM IV: long ATM straddle (or strangle if you want cheaper) into the move, exit on IV peak (typically 30–120s post-headline). The asymmetry is large because most of the time the news is already priced.

**Latency budget.** End-to-end news → trade signal: ingest 0.5s + dedupe 0.1s + LLM scoring 3–5s + vol model 0.05s + alert 0.1s = **~6s P99**. Versus Bloomberg/Reuters terminal users at ~1s. You will lose to them on the genuinely fast headlines, but most of the alpha is in the slower-decay news (Fed speeches, scheduled reports) where 6s is plenty.

---

## 7. The $500/mo Data Stack I Would Actually Build

```
Subscriptions
─────────────
SpotGamma Standard    $129  → dealer GEX, gamma flip, HIRO, vanna/charm
Polygon.io Options Adv $199  → real-time options, 15y history, news
Unusual Whales basic  $ 48  → sweeps + congress real-time
NewsAPI.ai Pro        $ 99  → news firehose
Anthropic API budget  $ 50  → LLM scoring (with caching)
                     ─────
                      $525/mo
```

**Free layer.** FRED, EDGAR, Treasury Direct, Federal Reserve speeches, CBOE EOD, SEC RSS, Reddit (PRAW), pytrends, snscrape (Twitter), Glassnode free tier.

**Existing.** Schwab (real-time SPX/VIX/options), Tradier (already in code), Alpaca (paper for execution validation).

**Architecture.**

```
ingest/                  normalize/             feature/
─────                    ─────────              ────────
schwab.py     ──┐                              gex_features.py
tradier.py    ──┤                              vol_term.py
polygon.py    ──┼→ canonical_event ─→ DuckDB → news_features.py ─→ FeatureBundle
spotgamma.py  ──┤   (event_time,                                       │
unusual.py    ──┤    ingest_time,                                      ▼
news.py       ──┤    payload, src,                              swarm/strategy
fred.py       ──┘    schema_v)                                  selector / agents
twitter.py    ──┘                              monitor/
edgar.py      ──┘                              ─────── dq_monitor.py (alert on stale)
fed_rss.py    ──┘                              recon.py (cross-source diff)
```

**Caching.** Three layers:
1. In-memory LRU (1–5s) for hot quote/chain reads — keeps swarm cycles cheap.
2. DuckDB tick store (forever) — every payload hashed and deduped, append-only with schema versioning.
3. Disk pickle cache (24h TTL) for slow EOD pulls (FRED, CBOE EOD, ETF flows).

Use `diskcache` for the third layer, not custom file IO.

**Storage.** DuckDB is fine for ≤500GB. Beyond that, Parquet partitioned by `date/asset/source` on local SSD. RTX 4090 box can hold 5y of OPRA in <2TB.

---

## 8. What Hedge Funds Buy That Retail CANNOT

**The genuinely-cripping moats.**

- **NYSE OpenBook / Nasdaq TotalView.** Full L2 order book, ITCH-level. $5k–$30k/mo per venue. Needed for order-book-microstructure alpha (price impact prediction, queue position modeling). Retail cannot reach the latency or depth.
- **Bloomberg / Refinitiv tick data going back decades.** Cleaned, point-in-time correct, all venues. ~$50k+/yr. The painful part isn't the data — it's the cleaning. You cannot buy 1995 SPX option ticks anywhere as cheaply as Bloomberg sells them.
- **Satellite imagery.** Orbital Insight, RS Metrics — $25k–$200k/yr. Parking lots, oil-tank levels, China port traffic. Useful for individual names, marginal for SPX 0DTE.
- **Credit-card panel data.** Yipitdata, Earnest, Second Measure — $50k–$500k/yr. Pre-earnings signal for retail/consumer names. Marginal for SPX index.
- **Web-traffic and app-usage panels.** Similarweb, Sensor Tower. $20k+/yr. Same — single-name alpha, not index alpha.
- **Custodian and prime-broker holdings.** Internal only. Real edge — citadel knows who's long what.

**Where retail's disadvantage is NOT crippling for SPX 0DTE.**

This is the underrated point: for **SPX 0DTE specifically**, the disadvantage is small. SPX is the most-replicated, most-arbitraged, most-public number on Earth. Dealer GEX, VIX term structure, 0DTE flow imbalance — *these are public data*. SpotGamma's GEX is the same GEX a fund computes in-house. The fund computes it 50ms faster, but for an event-driven retail trader holding minutes-to-hours, 50ms is irrelevant.

Where retail loses on SPX 0DTE:
- **Execution slippage.** Mid-fill probability is much lower than what funds get with broker direct routes.
- **Capital constraints.** Cannot size up after positive expectancy is established.
- **Flow visibility.** A fund seeing its own clients' flow has private signal.

What retail does NOT lose:
- The ability to *predict* SPX 0DTE direction from public data. The information set is roughly equivalent.

---

## 9. Three Alt-Data Angles I Don't Think Anyone Is Exploiting (At Retail Scale)

**1. Real-time SEC Form 4 cluster detection on SPX components.** Form 4s are public and filed within 2 business days. Build a streaming detector that flags when ≥5 SPX-component insiders buy in the same week. This precedes 5–10 trading-day positive drift in the historical sample (replicated in academic literature, e.g. Cohen-Malloy-Pomorski). Nobody at retail watches the full SPX cluster — they watch individual names. Build the index-level signal. 100% free via EDGAR.

**2. Federal Reserve speech corpus diff against prior speeches by the same speaker.** Don't score speeches in isolation — score the *delta* against the speaker's last 5 speeches. A Powell speech that uses "transitory" half as often as last time is the actual signal, not the absolute hawk/dove score. Nobody productizes per-speaker drift. Free via federalreserve.gov + sentence-embedding model + Anthropic for explanation.

**3. Cross-asset divergence regime tag from a learned manifold.** Ingest SPX, VIX, DXY, HYG, TLT, BTC, ES basis, gold, copper. Learn a 2D manifold with UMAP refit nightly. Tag the current state vs historical neighbors. When today is a 3+ sigma outlier from its 60-day neighbors → "regime stress" tag → swarm switches to defensive prompt template, agents weight macro voices higher. Most retail looks at single-asset divergences (VIX vs SPX). Few build the joint manifold and almost none use it as a *prompt-conditioning* signal for an agent system. This is exactly where SwarmSPX's swarm architecture has an asymmetric advantage — the manifold tells the swarm *which agents to listen to*.

(Bonus 4: a follow-graph-weighted FinTwit signal where each post is weighted by the *follower-trader-influence* of the author, computed via a once-monthly graph PageRank on the FinTwit subgraph. Retail FinTwit aggregators do flat counts. The PageRank-weighted version is dramatically less noisy.)

---

## Data Stack Recommendation

| Tier | $0/mo | $200/mo | $500/mo | $2,000/mo |
|---|---|---|---|---|
| **Quotes** | yfinance, Schwab (you have it) | + Polygon Stocks Starter ($29) | + Polygon Stocks Adv ($199) | + IBKR + OPRA bundle |
| **Options** | Tradier, Schwab | Polygon Options Starter ($29) | Polygon Options Adv ($199) | CBOE LiveVol + OptionMetrics |
| **GEX / Dealer Flow** | DIY GEX from CBOE OI (rough) | SpotGamma Standard ($129) | SpotGamma Standard ($129) | SpotGamma Pro ($499) + Sentinel |
| **Flow / Sweeps** | none | Unusual Whales basic ($48) | Unusual Whales basic ($48) | Unusual Whales institutional |
| **News** | RSS scraping, Fed RSS, EDGAR | NewsAPI.ai Starter | NewsAPI.ai Pro ($99) | + Benzinga Pro + Dataminr lite |
| **Macro** | FRED, Treasury Direct | + Quandl one-offs | FRED + ALFRED | Bloomberg-lite (Polygon Enterprise) |
| **Sentiment** | snscrape, Reddit, pytrends | + Finnhub ($50) | + Finnhub + Quiver Pro ($100) | + Sentiment-tagged FactSet |
| **LLM scoring** | Ollama local (Phi-4, Llama 8B) | OpenAI/Anthropic ($30) | Anthropic API ($50) | Anthropic Enterprise + fine-tunes |
| **Backtest** | Polygon free EOD | Polygon Options Starter | Polygon Options Adv 15y | OptionMetrics Ivy |
| **Total** | $0 | ~$200 | ~$525 | ~$2,000–$3,000 |
| **Realistic IR uplift on current SwarmSPX** | +0.2 (via Form 4 cluster + Fed delta) | +0.5 (Polygon + UW) | **+1.0 (the sweet spot)** | +1.2 (diminishing returns) |

The marginal product of the $500 tier is the steepest. Above $500/mo, you are mostly buying redundancy, latency, and history depth — useful but not 1:1 with edge for SPX 0DTE.

**Where to start tomorrow.** Add SpotGamma Standard, Polygon Options Advanced, and wire your Finnhub key. Build the Form 4 cluster detector and Fed-speech-delta scorer over the weekend. That's the v2 that beats v1 by a real, measurable margin — and the data hygiene layer (point-in-time, monitoring, reconciliation) is what keeps you honest when the model says you have edge.
