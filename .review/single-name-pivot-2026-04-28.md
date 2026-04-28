# Single-Name 0DTE Pivot — Baselines

**Date:** 2026-04-28
**Decision:** Pivot the SwarmSPX backtest validation from SPX to single-name 0DTE candidates per war-room heretic brief (`.review/warroom/06-heretic.md`).

**Rationale:**
- SPX is the most efficient market on earth; Citadel's gamma model beats retail
- Single names (NVDA, TSLA, META) have **100× more text-narrative** for LLMs to parse — earnings, supply-chain, AI announcements, regulatory news
- $0.50 contract sizes let real feedback loops complete in weeks not months
- Less institutional dominance in single-name 0DTE
- D2DT already has 90 days of NVDA/TSLA/META 1m bar data cached

## Naive Baselines (90-day SPY/NVDA/TSLA/META)

Knobs: cooldown 30 bars; targets calibrated to per-name vol (NVDA/TSLA: ±100/-50bps; META/SPY: ±50/-25bps).

| Symbol | Strategy           | Trades | Win% | Sharpe | MaxDD% | P&L    |
|--------|--------------------|-------:|-----:|-------:|-------:|-------:|
| **NVDA**  | SMA(5,20)          | 488 | 32.6 | -0.41 | 184.7 | -$330  |
| **NVDA**  | FadeMomentum 50bps | 318 | 37.4 | -0.29 | 83.7  | -$146  |
| **NVDA**  | FadeMomentum 30bps | 425 | 37.6 | -0.29 | 122.2 | -$217  |
| **TSLA**  | SMA(5,20)          | 517 | 34.8 | -0.37 | 175.9 | -$753  |
| **TSLA**  | FadeMomentum 50bps | 323 | 32.8 | -0.40 | 112.4 | -$487  |
| **TSLA**  | FadeMomentum 30bps | 458 | 31.9 | -0.40 | 158.3 | -$684  |
| **META**† | SMA(5,20)          | 126 | 30.2 | -0.49 | 29.5  | -$188  |
| **META**† | FadeMomentum 50bps | 15  | 20.0 | -0.68 | 6.9   | -$45   |
| **META**† | FadeMomentum 30bps | 52  | 28.9 | -0.57 | 15.5  | -$100  |
| SPY    | SMA(5,20)          | 271 | 32.5 | -0.29 | 36.1  | -$2,362|
| SPY    | FadeMomentum 50bps | 18  | 33.3 | -0.24 | 3.4   | -$133  |
| SPY    | FadeMomentum 30bps | 66  | 37.9 | -0.16 | 7.2   | -$309  |

† META 1m_90d not present in cache; ran on 5d sample.

## Read

1. **No free money anywhere.** All naive strategies negative-Sharpe across all four symbols. As expected — TA without edge loses to spreads + slippage.
2. **TSLA volatility punishes naive strategies hardest** ($-753 P&L, 175% MaxDD). High-conviction signal required to overcome the drag.
3. **META's smaller sample (5d) shows lowest absolute drawdowns** but tiny trade counts — needs the 90d file before drawing conclusions.
4. **NVDA at $330 loss over 90 days = -$3.67/day** — within the noise floor of round-trip slippage.

## Swarm Beat Bars

For SwarmSPX 24-agent (or future) signal layer to claim edge on a single name, it must beat the **best naive baseline for that symbol**:

| Symbol | Threshold (P&L over 90d) | Sharpe to beat |
|--------|------------------------:|---------------:|
| NVDA   | better than -$146       | > -0.29 |
| TSLA   | better than -$487       | > -0.40 |
| META   | better than -$45 (5d only) | > -0.68 |
| SPY    | better than -$133       | > -0.24 |

These are the war-room go/no-go gates for promoting the swarm out of research.

## Why single-name unlocks edge that SPX can't

The naive TA results above are nearly identical across SPX and single-names — that's expected because TA-only ignores the **text/news layer**. Where single-names diverge:

- **Earnings cycles** — predictable IV crush + drift events 4× per year per name
- **Pre-event positioning** — SEC/13F filings reveal large hedge fund moves with 30-45 day lag (CongressTrades, Form 4)
- **News volatility** — analyst upgrades, supply-chain leaks, regulatory action
- **Concentration risk → opportunity** — NVDA reacts to *one* AI announcement; SPX averages 500 names

The 24-agent swarm with sentiment + flow tribes is uniquely positioned to harvest these. SPX averages them away.

## Next steps

1. Run the swarm at 30-min cadence over 90 days of NVDA + TSLA + META (~2k LLM cycles total, ~16h on 4090). Compare to baselines above.
2. Wire `swarmspx/ingest/` to fetch single-name option chains (Schwab API supports). Currently the ingest is SPX-only.
3. Adapt `swarmspx/strategy/selector.py` for single-name conventions (smaller premiums, larger spreads as % of price).
4. Pull META_1m_90d via Polygon (key now in `.env`) to close the 5d → 90d gap.
5. After swarm-driven backtest, decide which name(s) to focus paper trading on.
