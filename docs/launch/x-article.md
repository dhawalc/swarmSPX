# I Built an AI Trading Pit: 24 Agents Debate SPX 0DTE Trades in Real-Time

What if instead of one AI giving you a trading signal, you had 24 AI agents — each with a different strategy — arguing about it first?

That's SwarmSPX. It's open source. You can run it yourself.

github.com/dhawalc/swarmspx

---

## The Problem with Single-Model Trading Signals

Every AI trading tool I've seen works the same way: feed data to one model, get one answer. But that's not how real trading floors work.

On a real desk, the gamma trader disagrees with the macro guy. The risk manager vetoes the momentum trader. The contrarian fades the consensus. The best signals emerge from structured disagreement — not from one brain, no matter how smart.

So I built a swarm.

---

## 24 Agents, 4 Tribes, 3 Rounds of Debate

SwarmSPX spawns 24 trader-agent personas organized into 4 tribes:

**Technical Tribe** — VWAP Victor (mean reversion), Gamma Gary (dealer hedging flows), Delta Dawn (scalping), Momentum Mike (breakouts), Level Lucy (support/resistance), Tick Tina (NYSE internals)

**Macro Tribe** — Fed Fred (rates policy), Flow Fiona (dark pool tracking), VIX Vinny (volatility regime), GEX Gina (gamma exposure), Put-Call Pete (sentiment ratios), Breadth Brad (market breadth)

**Sentiment Tribe** — Twitter Tom (social sentiment), Contrarian Carl (fade the crowd), Fear Felicia (fear/greed), News Nancy (event-driven), Retail Ray (fade retail), Whale Wanda (institutional blocks)

**Strategist Tribe** — Calendar Cal (theta decay), Spread Sam (defined-risk spreads), Scalp Steve (1-5min scalps), Swing Sarah (multi-hour swings), Risk Rick (position sizing), Synthesis Syd (meta-analyst)

Each agent has a unique persona, bias, and specialty. They don't just label BULL or BEAR — they reason about WHY based on their expertise.

---

## How the Swarm Thinks

1. **Ingest** — Fetch live SPX price, VIX, VWAP, change % from the market

2. **Round 1** — All 24 agents independently analyze the data through their lens. No groupthink. Pure independent opinion.

3. **Round 2** — Each agent sees the swarm's current distribution (e.g., "15 BEAR, 6 BULL, 3 NEUTRAL") plus the strongest bull and bear cases. They can change their mind — or dig in harder.

4. **Round 3** — Final positions. By now, weak convictions have shifted and strong convictions have hardened.

5. **Consensus Extraction** — The system calculates direction, confidence (weighted by conviction), agreement percentage. It detects herding (too many agents flipping at once) and contrarian alerts (high-conviction minority dissenting).

6. **Trade Card Synthesis** — A synthesis model produces a specific, actionable 0DTE trade recommendation: instrument, entry, target, stop, rationale, key risk, time window.

The magic isn't any single agent. It's the emergent signal from 24 different analytical lenses converging (or not converging) on a view.

---

## The Visualization

This is where it gets fun.

The web dashboard shows a real-time neural network of all 24 agents. Each node glows with its direction (green = BULL, red = BEAR). Neural connections light up between agents that agree. Data particles flow along the connections from high-conviction agents to low-conviction ones — you can literally watch influence propagate through the swarm.

When the swarm reaches consensus, a shockwave ripple floods the entire canvas. It feels like watching a hive mind make a decision.

There's a debate room showing each agent's reasoning as they vote. You can hover over any node to see the agent's full personality card — their strategy, current position, and reasoning.

Press F for cinematic full-screen mode. Perfect for recording.

---

## The Tech

- Python + asyncio
- 18 agents run locally on Llama 3.1 8B via Ollama (fast, ~3-5 sec per batch)
- 6 strategist agents use Claude Sonnet via Claude Code CLI (deeper reasoning, Max plan OAuth — no API key costs)
- Neural network visualization: vanilla HTML Canvas, zero framework dependencies
- FastAPI + WebSocket for real-time event streaming
- DuckDB for local storage
- EventBus architecture decouples the engine from any UI
- Telegram + Slack alerts when swarm confidence exceeds 70%

Runs on a single RTX 4090. All local except the 6 strategist agents.

---

## What I Learned Building This

**Swarm > Poll.** With small models, the agents give surface-level takes ("VIX high so bearish"). With better models on the strategist tribe, you get actual second-order reasoning ("positive GEX suppresses vol, so this bearish pressure likely fades by 2pm"). The debate becomes substantive.

**Herding detection matters.** In early tests, all 24 agents would converge to the same direction by round 3. That's not consensus — that's echo chamber. The herding detector catches this and flags it as unreliable.

**Contrarian alerts are the alpha.** When 20 agents say BULL but 2 agents say BEAR at 90%+ conviction — that minority view often contains the insight the majority missed. The system surfaces these explicitly.

**The visualization sells the concept.** Without the neural network UI, this is just another AI signal generator. Watching the agents think in real-time — seeing connections form, nodes flip, conviction arcs grow — transforms it from a tool into an experience.

---

## What's Next

This is v1. Shipping updates daily, building in public:

- **v1.1** — Real options chain data via Tradier API (actual strikes, premiums, Greeks)
- **v1.2** — Outcome tracking: did the swarm's prediction hit? Feed results back so it learns from its own history
- **v1.3** — Voice mode: hear the agents debate (TTS)
- **v2.0** — Paper trade auto-execution via Alpaca
- **v2.1** — Historical backtesting: how would the swarm have performed over the last year?
- **v3.0** — Custom agent personas: bring your own trading thesis in YAML

---

## Try It

It's fully open source under MIT license.

github.com/dhawalc/swarmspx

```
git clone https://github.com/dhawalc/swarmSPX.git
cd swarmSPX
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m swarmspx.cli web --port 8420
```

Star it, fork it, add your own agent personas. PRs welcome.

Inspired by MiroFish's multi-agent swarm intelligence concept — the idea that a diverse swarm of specialized agents produces better signals than any single model, no matter how large.

Building in public. Let's see where this goes.

— @dhawalc
