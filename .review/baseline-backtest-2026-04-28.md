# Honest Baseline Backtest — 2026-04-28

**Data:** D2DT/SPY_1m_90d.parquet (60k rows, 2025-11-17 → 2026-02-23)
**Multiplier:** SPY × 10 = SPX-equivalent
**Targets:** +50bps win / -25bps stop / 30-bar cooldown

## Results

| Strategy | Trades | Win% | Sharpe | Sortino | MaxDD% | Calmar | P&L (USD) |
|---|---:|---:|---:|---:|---:|---:|---:|
| always_wait | 0 | 0.0 | 0.000 | 0.000 | 0.00 | 0.00 | $0.00 |
| SMA_5_20 | 271 | 32.5 | -0.292 | -0.279 | 36.08 | -0.96 | $-2,361.74 |
| FadeMomentum_30bps | 66 | 37.9 | -0.164 | -0.166 | 7.21 | -0.62 | $-309.12 |

## Interpretation

- **Null hypothesis () produces 0 trades, $0 P&L** — the execution pipeline does NOT generate phantom trades. Confirms baseline correctness.
- **Naive SMA(5,20) crossover loses $2,362 over 90 days** (-0.29 Sharpe, 36% drawdown).
- **FadeMomentum loses less** but still negative (-0.16 Sharpe).

## War-room threshold

For the SwarmSPX 24-agent swarm to claim edge, it must beat BOTH baselines on the same data window. Until that's demonstrated, all marketing claims about edge are noise.

## Honest caveats

1. **SPY proxy.** SPX has different overnight gap behavior; the SPY×10 approximation is reasonable for intraday but biased for overnight events.
2. **No option pricing.** The runner closes positions on SPX move (basis points), not actual option premium delta. Real 0DTE option P&L is more asymmetric (theta crush makes losses bigger and winners bigger). Refine via Polygon Options Advanced.
3. **No regime filter.** Trades fired in panic vol the same as in chop. Adding regime gates likely flips at least one of these to positive.
4. **No GEX overlay.** The selectors used here are pure price-based. The dealer-positioning edge from  is not applied.

## Next

Wire the GEX-aware selector + risk gate + Kelly sizer into a swarm-driven backtest at low frequency (e.g., 1 decision per 30 minutes) so the LLM cost is bounded. Compare to these baselines.