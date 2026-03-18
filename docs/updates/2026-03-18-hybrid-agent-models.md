# SwarmSPX Update: Hybrid Agent Model Strategy

**Date:** 2026-03-18
**Config changes:** synthesis_model changed to `phi4:14b`, num_rounds reduced to 3

---

## Discussion: Upgrading Agent Intelligence

### Current Setup
- **Agent model:** Llama 3.1 8B (all 24 agents)
- **Synthesis model:** phi4:14b (trade card generation)
- **Rounds:** 3 per cycle

### Problem with 8B Models
- Gives surface-level reasoning ("VIX is high so bearish")
- Swarm behaves as a **poll**, not a **debate**
- Agents acknowledge AOMS memories but don't incorporate them meaningfully
- Herding/contrarian detection is less meaningful because agents lack nuanced positions

### What Sonnet 4.6 Would Change
- Actually understands GEX, gamma exposure, options flow dynamics
- Reasons about second-order effects: "positive GEX suppresses vol which means this bearish pressure is likely to fade by 2pm"
- Incorporates AOMS memories meaningfully
- Produces reasoning you'd actually learn from
- Transforms the swarm from a **poll** into an **actual debate** with substantive disagreement

### Cost Concern
- 24 agents x 3 rounds = 72 API calls per cycle
- At 5-minute intervals = ~864 calls/hour
- Anthropic API costs add up fast at that volume

### Proposed Approach: Hybrid Model Strategy
Use Sonnet for the **6 Strategist tribe agents** (whose reasoning matters most) and keep Llama 3.1 8B for the other 18 agents.

**Sonnet agents (6):** calendar_cal, spread_sam, scalp_steve, swing_sarah, risk_rick, synthesis_syd
**Llama agents (18):** All technical, macro, and sentiment tribe agents

This gets quality reasoning where it counts at ~20% of the full Sonnet cost.

### Alternative: Opus for Synthesis Only
Use Opus 4.6 as the synthesis_model (replacing phi4:14b) so the final trade card benefits from the deepest reasoning, while keeping agent chatter on cheaper models.

---

## Next Steps
- [ ] Wire up per-tribe model override in config/agents.yaml
- [ ] Add Anthropic API support alongside Ollama (OpenAI-compatible endpoint)
- [ ] Implement hybrid model routing in AgentForge
- [ ] Benchmark quality difference: Llama-only vs hybrid vs full-Sonnet
