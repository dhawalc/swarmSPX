# 04-architect.md — SwarmSPX Target Architecture

**Author:** Systems Architect (war room)
**Date:** 2026-04-27

## 0. Thesis

The current SwarmSPX (~7,200 LOC, asyncio + DuckDB + FastAPI + Ollama) is a respectable research harness. It is *not* a trading system. The gap is the absence of seven concrete subsystems that every prop shop has and no retail tool ships:

1. Point-in-time feature store (no lookahead, replayable)
2. Walk-forward backtester with a real fill model
3. Paper-trade simulator using the same code-path as live
4. Alpha-decay tracker
5. Regime detector that *gates* model output
6. Position-sizing engine with Kelly fractioning + volatility targeting
7. Multi-trigger kill switch

The 24-agent swarm is **one input among many** in the target architecture, not the system.

## 1. Reference Architecture

```
                          ┌──────────────────────────────────────────────┐
                          │               CONTROL PLANE                  │
                          │  Scheduler │ Kill Switch │ Config │ Secrets  │
                          └──────────────────────────────────────────────┘
                                          │
                                          ▼
┌──────────────┐   ┌──────────────┐   ┌────────────────┐   ┌──────────────┐
│  L1: INGEST  │──▶│ L2: FEATURES │──▶│ L3: MODEL      │──▶│ L4: DECISION │
│ Schwab WS    │   │ tick→1s→1m   │   │ • 24-agent     │   │ • signal mux │
│ Tradier      │   │ rolling agg  │   │ • XGBoost      │   │ • regime gate│
│ yfinance     │   │ GEX recon    │   │ • Greeks calc  │   │ • alpha-decay│
│ Finnhub news │   │ vol surface  │   │ • RegimeNet    │   │ • position   │
│ /ES futures  │   │ feature      │   │   FastAPI +    │   │   sizing     │
│              │   │ store (PIT)  │   │   Triton/Ollama│   │              │
└──────┬───────┘   └──────┬───────┘   └───────┬────────┘   └──────┬───────┘
       │                   │                   │                   │
       │                   ▼                   ▼                   ▼
       │           ┌──────────────────────────────────────────────────┐
       │           │  EVENT BUS — Redis Streams (later: Kafka)        │
       │           │  topics: ticks, features, signals, fills, audits │
       │           └──────────────────────────────────────────────────┘
       │                                       │
       │                                       ▼
       │                          ┌──────────────────────────┐
       │                          │  L5: PRE-TRADE RISK GATE │
       │                          │  • greeks delta limit    │
       │                          │  • daily loss band       │
       │                          │  • position concentration│
       │                          │  • idempotency token     │
       │                          └──────────┬───────────────┘
       │                                     ▼
       │              ┌──────────────────────────────────────┐
       │              │  L6: EXECUTION                       │
       │              │  • OMS state machine                 │
       │              │  • Smart router (Schwab → Alpaca)    │
       │              │  • Slippage model                    │
       │              │  • Reconciliation loop (5s)          │
       │              │  • Paper sim (shadow mode)           │
       │              └──────────────────────────────────────┘
       ▼
┌──────────────────────┐        ┌──────────────────────────────┐
│  STORAGE TIERS       │        │  L7: OBSERVABILITY + AUDIT   │
│  Hot:  Redis (24h)   │◀──────▶│  Prometheus + Grafana        │
│  Warm: Parquet+DuckDB│        │  Loki (JSON logs)            │
│  Cold: S3/B2 (>1y)   │        │  Per-decision audit log      │
└──────────────────────┘        │  Alpha-decay dashboard       │
                                │  Drift detector              │
                                └──────────────────────────────┘
```

Each layer is testable, replaceable, and scalable independently.

## 2. Migrate vs Keep

**Keep:** DuckDB (analytics), FastAPI (surfaces), 24-agent swarm (demoted to one signal source), Ollama on 4090 (Phi-4 14B + Llama 8B), Telegram alerts.

**Migrate:**

| Current | Move to | Why |
|---|---|---|
| DuckDB as hot path | Redis 7.4 (Streams + Hashes) | DuckDB write contention catastrophic at tick rate |
| In-memory EventBus | Redis Streams w/ consumer groups | Survives process restarts, replayable |
| `httpx.post()` blocking | `httpx.AsyncClient` + 2s timeout | Already a known bug (review #6, #H8) |
| Schwab REST polling | Schwab StreamClient WebSocket | Eliminates 120 req/min cap (#H9) |
| `datetime.now()` naive | `pendulum` + ET-anchored clock | Single bug class, single fix (#8) |
| `engine.run_cycle` no try/except | `asyncio.TaskGroup` w/ lifecycle states | Prevents stuck-running lock (#7) |

Boundary: durability/replayability/multi-consumer → Redis + Parquet. One-shot query → DuckDB. Request/response → FastAPI.

## 3. Data Pipeline

### 3.1 Ingest — record TWO timestamps

```
Schwab StreamClient (WS)  ──┐
Tradier WS (fallback)        ├──▶ ingest_normalizer.py ──▶ Redis Streams
yfinance polling (60s)       │     • timestamp_arrival_ns
Finnhub news WS              │     • timestamp_exchange_ns
                            ─┘     • source_id, seq_num
```

`t_exchange` minus `t_arrival` = latency. Alpha-decay early warning.

### 3.2 Aggregation

```
ticks (Redis stream, TTL 24h)
  ─▶ 1s bars (in-memory rolling 60s)
       ─▶ 1m bars (Parquet: yyyy/mm/dd/hh/spx_1m.parquet)
            ─▶ 5m / 15m / 1h / 1d (DuckDB views)
```

### 3.3 Real-Time GEX Reconstruction

```python
gamma_exposure = sum(
    contract.open_interest * contract.gamma * contract.contract_size
    * spx_price**2 * 0.01
    for contract in chain
)
```
Storage: `(timestamp, strike, expiry, gex_call, gex_put, net_gex)` → Redis Stream → Parquet. Replaces SpotGamma $199/mo with free CBOE OI.

### 3.4 Storage Tiers

| Tier | Tech | TTL | Use |
|---|---|---|---|
| Hot | Redis 7.4 | 24h | Live decisions, last-N quotes |
| Warm | Parquet (Snappy) + DuckDB | 1y | Backtests, dashboards |
| Cold | Backblaze B2 ($6/TB/mo) | indefinite | Audit, retraining |

### 3.5 Point-in-Time Correctness — non-negotiable

Every feature row has TWO timestamps:
- `as_of_time` — when feature is *valid* (bar close)
- `available_time` — when *knowable* to trader (`as_of_time + processing_lag`)

Backtests filter on `available_time <= sim_clock`. **Eliminates 90% of backtest fraud.** Reference: "as-of join" pattern at Two Sigma, Citadel, AQR.

```sql
SELECT * FROM features
WHERE symbol = 'SPX'
  AND available_time <= TIMESTAMP '2024-03-15 09:35:00'
  AND as_of_time = (
    SELECT MAX(as_of_time) FROM features
    WHERE symbol='SPX' AND available_time <= TIMESTAMP '2024-03-15 09:35:00'
  );
```

## 4. Execution Architecture

### 4.1 Order State Machine

```
   ┌──────┐ submit  ┌─────────┐ ack   ┌─────────┐ fill  ┌────────┐
   │ DRAFT│────────▶│ PENDING │──────▶│ WORKING │──────▶│ FILLED │
   └──────┘         └────┬────┘       └────┬────┘       └───┬────┘
                         │ reject          │ cancel         │
                         ▼                 ▼                ▼
                    ┌────────┐       ┌──────────┐     ┌──────────┐
                    │REJECTED│       │ CANCELED │     │ MANAGING │
                    └────────┘       └──────────┘     └────┬─────┘
                                                           │ exit
                                                           ▼
                                                      ┌────────┐
                                                      │ CLOSED │
                                                      └────────┘
```

### 4.2 Idempotency

`client_order_id = sha256(strategy_id|signal_id|leg_id|cycle_ts)`. Broker rejects duplicates. The single line of code between losing $0 and losing $50k to a double-fire.

### 4.3 Reconciliation Loop

```python
async def reconcile_loop():
    while True:
        broker_positions = await schwab.get_positions()
        local_positions  = await db.get_open_positions()
        diff = symmetric_diff(broker_positions, local_positions)
        if diff:
            audit_log.error("RECONCILE_DRIFT", diff=diff)
            kill_switch.trigger("reconcile_drift")
        await asyncio.sleep(5)
```

### 4.4 Circuit Breakers

```yaml
circuit_breakers:
  daily_loss_band:    { threshold_pct: -2.0, action: pause_24h }
  weekly_loss_band:   { threshold_pct: -5.0, action: pause_week }
  max_open_positions: { count: 5,            action: reject_new }
  data_staleness:     { max_age_seconds: 30, action: pause_until_fresh }
  latency_p99:        { max_ms: 500,         action: alert_only }
  reconcile_drift:    { tolerance: 0,        action: kill_all }
  manual_kill:        { trigger: telegram,   action: kill_all }
```

## 5. Backtesting Infrastructure

### 5.1 Event-Driven Simulator

```
historical_ticks (Parquet)
  ─▶ EventReplayer (yields events in t_exchange order)
       ─▶ SimClock (advances on each event)
            ─▶ Same code path as live
                 ─▶ SimulatedExchange (fill model)
                      ─▶ PnL ledger
                           ─▶ Metrics (Sharpe, Sortino, MaxDD, Calmar)
```

### 5.2 Slippage Model

```python
def simulate_fill(order, l2_book_snapshot, latency_ms):
    book_at_arrival = advance_book(l2_book_snapshot, latency_ms)
    half_spread = (book.ask - book.bid) / 2
    impact = walk_book(order.size, book_at_arrival)
    if order.type == 'LMT':
        fill_prob = queue_position_model(order.price, book_at_arrival)
        if random() > fill_prob: return None
    return Fill(price=mid + half_spread + impact, ...)
```

### 5.3 Pitfalls

| Bias | Mitigation |
|---|---|
| Survivorship | Historical universe snapshots |
| Lookahead | `available_time` discipline |
| Anti-aliasing | Tick-level entries, bars for features |
| Rebalance | Charge fees on every state transition |
| Borrow / financing | Model SOFR + 50bps overnight |
| Dividend / split | Adjust at corporate-action level |

### 5.4 Walk-Forward

```
[train 2020-01 → 2020-12] [test 2021-Q1]
  [train 2020-04 → 2021-03] [test 2021-Q2]
    [train 2020-07 → 2021-06] [test 2021-Q3]
```

Threshold: Sharpe > 1.0 across ≥60% of windows. Reference: López de Prado, *Advances in Financial Machine Learning*, Ch. 7.

## 6. Observability

- **Metrics:** Prometheus + Grafana
- **Logs:** structured JSON, every line has `cycle_id`, `signal_id`, `agent_id`, `ts`, `level`
- **Traces:** OpenTelemetry → Tempo

### Alpha-Decay Dashboard

```
Panel 1: Rolling Sharpe (30d, 90d, 365d)
Panel 2: Win rate by regime
Panel 3: Avg P&L per signal (last 100 / 500 / 2000)
Panel 4: Agent ELO drift (heatmap)
Panel 5: Slippage realized vs predicted
Panel 6: Latency p50/p95/p99 per stage
```

**The alert that matters:** rolling 30d Sharpe drops below 50% of rolling 365d Sharpe → page yourself.

### Drift Detection
KS statistic per feature between training distribution and last-24h. >30% drifted → auto-pause.

## 7. Risk Infrastructure

### Pre-Trade Gate (synchronous, blocking, 50ms budget)

```python
def pre_trade_check(order, portfolio, market) -> RiskDecision:
    checks = [
        check_daily_loss_band(portfolio),
        check_position_concentration(order, portfolio),
        check_buying_power(order, portfolio),
        check_greeks_limits(order, portfolio),
        check_position_count(portfolio),
        check_idempotency(order),
        check_data_freshness(market),
    ]
    if any(c.rejected for c in checks):
        audit_log.warn("PRE_TRADE_REJECT", checks=checks)
        return RiskDecision.REJECT
    return RiskDecision.PASS
```

### Stress Tests (nightly)
- CPI surprise: SPX -3% in 5 min, VIX +30%
- FOMC hawkish: SPX -2%, vol crush
- Banking event: VIX +50%, correlation breakdown
- Quarterly OpEx: gamma flip, pin to round strikes

Alert if any scenario < -10% NAV.

## 8. Cloud vs Local

| Component | Where | Why |
|---|---|---|
| Schwab WS ingest | VPS (Hetzner CX22 €4/mo) | 99.99% uptime |
| Redis | Same VPS, 2GB | Co-located |
| Scheduler + execution | VPS | Uptime |
| Model inference | 4090 at home | $0 marginal |
| Backtester | 4090 at home | DuckDB on NVMe + 24GB VRAM |
| Dashboard | VPS | Public-facing |
| Cold storage | Backblaze B2 | $6/TB/mo |

Wireguard tunnel from VPS → home for model serving. Total infra: ~€4/mo.

**Leave local entirely when:** capital > $50k OR strategy needs <100ms decision-to-fill.

## 9. Migration Plan — 6 Phases

### Phase 1 (M1): Feature Store + Honest Backtester
Build PIT feature store + event-driven backtester + slippage model. Replay 12 months of SPX through current swarm.
**Exit:** rolling Sharpe on real data; honest evaluation.

### Phase 2 (M2): Hot Path to Redis
Stand up Redis on VPS. Wire Schwab StreamClient. Move EventBus to Redis Streams.
**Exit:** zero data loss across 1 week; survives restart.

### Phase 3 (M3): Risk Gate + Paper Trading
Build pre-trade gate + paper sim. 30 days shadow paper.
**Exit:** ≥30 days paper P&L; <1bp reconciliation drift.

### Phase 4 (M4): Regime Detector + Position Sizing
HMM or k-means regime classifier. Kelly sizer × vol target × regime confidence.
**Exit:** ≥20% drawdown reduction in backtest, ≥80% return retained.

### Phase 5 (M5): Observability
Prometheus + Grafana, alpha-decay dashboard, drift detector, audit log.
**Exit:** every decision queryable end-to-end <2s; one full month of metrics.

### Phase 6 (M6): Live Execution
Smart router live. Order state machine. Reconciliation loop. Kill switch chaos-tested.
**Exit:** 30 days live at 0.1× size; zero unreconciled positions; zero double-fires; one chaos test recovered cleanly.

## 10. The 5 Things That Don't Exist Yet

Build in order. Existential.

1. **Point-in-time feature store** — without it, every backtest is a lie
2. **Honest event-driven backtester with slippage** — current is synthetic
3. **Pre-trade risk gate** — currently zero risk checks
4. **Reconciliation loop + idempotent order IDs** — without these, live is reckless
5. **Kill switch + circuit breakers** — multi-trigger, hardware-backed

Everything else is optimization.

## Phased Gantt

```
Month  │ 1  │ 2  │ 3  │ 4  │ 5  │ 6  │
───────┼────┼────┼────┼────┼────┼────┤
P1 FS  │████│    │    │    │    │    │  Feature store + backtester
P2 RDS │    │████│    │    │    │    │  Redis hot path + streams
P3 RSK │    │    │████│    │    │    │  Risk gate + paper sim
P4 RGM │    │    │    │████│    │    │  Regime + sizing
P5 OBS │    │    │    │    │████│    │  Observability stack
P6 LIV │    │    │    │    │    │████│  Live exec, scaled to 0.1x
───────┴────┴────┴────┴────┴────┴────┘
```
