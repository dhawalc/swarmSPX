# SwarmSPX

**24 AI agents debate SPX 0DTE trades in real-time. Watch the neural swarm think.**

<!-- Add your screenshot/video here -->
<!-- ![SwarmSPX Neural Network](docs/screenshots/neural-network.png) -->

---

## What is this?

SwarmSPX is a local multi-agent swarm intelligence engine for SPX options trading. It spawns 24 trader-agent personas — each with a unique strategy, bias, and specialty — feeds them live market data, and simulates a multi-round trading pit debate. The swarm argues, shifts positions, detects herding, and produces an actionable 0DTE trade card with confidence scoring.

## How it works

```
Live Market Data (SPX, VIX, VWAP)
        │
        ▼
┌─────────────────────────────────┐
│   24 Agent Personas (4 tribes)  │
│   Technical │ Macro │ Sentiment │
│         Strategists             │
└─────────────────────────────────┘
        │
        ▼ Round 1: Independent analysis
        ▼ Round 2: See peers, shift or dig in
        ▼ Round 3: Final positions
        │
        ▼
┌─────────────────────────────────┐
│   Consensus Extraction          │
│   Direction │ Confidence │ %    │
│   Herding detection             │
│   Contrarian alerts             │
└─────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────┐
│   Trade Card Synthesis          │
│   BUY SPX 6700P 0DTE           │
│   Entry $18.50 → Target $35    │
│   Stop $9 │ Window: 1-2 hours  │
└─────────────────────────────────┘
        │
        ▼
  Telegram + Slack Alerts
```

## The 24 Agents

### Technical Tribe
| Agent | Strategy |
|-------|----------|
| VWAP Victor | Mean reversion to VWAP |
| Gamma Gary | Gamma exposure hedging |
| Delta Dawn | Delta-neutral scalping |
| Momentum Mike | Breakout & trend following |
| Level Lucy | Support & resistance |
| Tick Tina | Market internals (TICK, TRIN, ADD) |

### Macro Tribe
| Agent | Strategy |
|-------|----------|
| Fed Fred | FOMC & rates policy |
| Flow Fiona | Dark pool & options flow |
| VIX Vinny | Volatility regime timing |
| GEX Gina | Gamma exposure levels |
| Put-Call Pete | Put/call ratio sentiment |
| Breadth Brad | Market breadth & internals |

### Sentiment Tribe
| Agent | Strategy |
|-------|----------|
| Twitter Tom | Social media sentiment |
| Contrarian Carl | Fade the crowd |
| Fear Felicia | Fear & greed mean reversion |
| News Nancy | Breaking news & event-driven |
| Retail Ray | Fade retail flow patterns |
| Whale Wanda | Large block & institutional detection |

### Strategist Tribe (Claude Sonnet powered)
| Agent | Strategy |
|-------|----------|
| Calendar Cal | Time decay & expiry dynamics |
| Spread Sam | Defined-risk spread construction |
| Scalp Steve | 1-5 minute scalping |
| Swing Sarah | 1-4 hour swing trades |
| Risk Rick | Position sizing & risk management |
| Synthesis Syd | Cross-tribe consensus building |

## Quick Start

```bash
git clone https://github.com/dhawalc/swarmspx.git
cd swarmspx
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Add your credentials

# Start the web dashboard
python -m swarmspx.cli web --port 8420
# Open http://localhost:8420 and click RUN CYCLE
```

**Requirements:** Python 3.12+, Ollama running with `llama3.1:8b` model, RTX GPU recommended.

## Run Modes

| Command | Description |
|---------|-------------|
| `python -m swarmspx.cli web` | Web dashboard at localhost:8420 |
| `python -m swarmspx.cli tui` | Full-screen terminal UI |
| `python -m swarmspx.cli run` | Single cycle, Rich console output |
| `python -m swarmspx.cli run --loop` | Continuous 5-min schedule |

**Cinematic mode:** Press `F` in the web dashboard for a full-screen neural network view — perfect for screen recordings.

## Architecture

- **Python 3.12** + asyncio for concurrent agent execution
- **Ollama** (local) — 18 agents on Llama 3.1 8B
- **Claude Sonnet** (via CLI) — 6 strategist agents with deeper reasoning
- **FastAPI + WebSocket** — real-time event streaming to browser
- **Vanilla Canvas/JS** — neural network visualization, zero framework dependencies
- **DuckDB** — local storage for snapshots and simulation results
- **Textual** — alternative full-screen terminal UI
- **EventBus** — decoupled pub-sub architecture connecting engine to any UI

## Alerts

Configure in `.env`:
- **Telegram** — bot sends trade cards when confidence > 70%
- **Slack** — webhook posts with Block Kit formatting

## Inspiration

Inspired by [MiroFish](https://github.com/mirofish)'s multi-agent swarm intelligence concept — the idea that a diverse swarm of specialized agents produces better signals than any single model.

## Roadmap

See [ROADMAP.md](ROADMAP.md) for what's coming next.

## License

MIT — see [LICENSE](LICENSE)

---

Built by [@dhawalc](https://x.com/dhawalc). Building in public, shipping daily.
