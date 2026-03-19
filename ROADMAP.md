# SwarmSPX Roadmap

## v1.0 — SHIPPED
- 24 AI trader-agent personas in 4 tribes
- 3-round debate simulation with herding/contrarian detection
- Neural network visualization with real-time WebSocket updates
- Consensus extraction + trade card synthesis
- Hybrid model routing (Llama 8B local + Phi-4 14B strategists)
- Telegram + Slack alerts
- Web dashboard + terminal TUI + CLI modes
- Cinematic full-screen mode for recordings

## v1.1 — SHIPPED
- Tradier API integration for live SPX options data
- Actual strike selection based on delta/premium (~0.30 delta targeting)
- Greeks-aware agent prompts and trade card synthesis
- Real bid/ask spreads, IV, delta in trade cards and alerts
- Graceful fallback when Tradier API key not configured

## v1.2 — SHIPPED
- Record each signal with entry SPX price and signal ID
- Track P&L resolution after 2h or EOD (WIN/LOSS/SCRATCH)
- Feed outcomes back to AOMS memory for learning loop
- Signal History panel in web dashboard
- GET /api/signals and /api/stats REST endpoints
- Outcome alerts via Telegram + Slack

## v3.0-lite — SHIPPED
- YAML-defined custom agent personas (config/custom_agents.yaml)
- Merge custom agents into swarm (up to 30 total, 6 custom slots)
- Unknown tribes fall back to fast_local model
- REST API: POST/DELETE /api/agents/custom for runtime management
- Validation: duplicate ID rejection, required fields, cap enforcement

## v1.3 — Voice Mode
- Text-to-speech for agent debate (hear them argue)
- Audio alerts for high-conviction signals
- "Trading pit" audio simulation

## v2.0 — Paper Trading Execution
- Alpaca API integration for paper trade execution
- Auto-execute when swarm confidence > 85%
- Position sizing via Risk Rick's Kelly criterion
- Real-time P&L tracking

## v2.1 — Historical Backtesting
- Replay historical SPX data through the swarm
- Measure hit rate, avg P&L, max drawdown
- Compare swarm vs individual agent performance
- Optimize debate rounds and agent weights

## v3.0-full — Custom Agent Marketplace
- Community agent marketplace
- Agent performance leaderboard
- Evolutionary agent selection (top performers survive)

---

Want to contribute? Open an issue or PR. Building in public, shipping daily.
