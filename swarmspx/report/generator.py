import json
import re
from openai import AsyncOpenAI
from datetime import datetime

class ReportGenerator:
    """Uses Qwen 32B to synthesize agent consensus into a trade card."""

    def __init__(
        self,
        ollama_base_url: str = "http://localhost:11434/v1",
        model: str = "qwen2.5:32b",
    ):
        self.client = AsyncOpenAI(base_url=ollama_base_url, api_key="ollama")
        self.model = model

    async def generate(self, consensus: dict, market_context: dict, aoms_memories: list[dict] = None) -> dict:
        """Generate a structured trade card from swarm consensus."""
        memories_str = ""
        if aoms_memories:
            memories_str = "Relevant past market memories:\n" + "\n".join(
                f"- {m.get('content','')[:150]}" for m in aoms_memories[:3]
            )

        prompt = f"""You are a senior trading analyst synthesizing a 24-agent swarm intelligence signal into a concrete 0DTE trade recommendation.

SWARM CONSENSUS:
- Direction: {consensus['direction']}
- Confidence: {consensus['confidence']:.0f}%
- Agent Agreement: {consensus['agreement_pct']:.0f}% ({consensus.get('vote_counts', {})})
- Contrarian Alert: {'YES - high-conviction minority dissenting' if consensus.get('contrarian_alert') else 'No'}
- Herding Warning: {'YES - agents may be following each other' if consensus.get('herding_detected') else 'No'}

MARKET STATE:
- SPX: ${market_context['spx_price']:.2f}
- VIX: {market_context['vix_level']:.1f}
- Regime: {market_context['market_regime']}
- SPX vs VWAP: {market_context.get('spx_vwap_distance_pct', 0):+.2f}%

BULL CASE: {consensus.get('strongest_bull', 'N/A')}
BEAR CASE: {consensus.get('strongest_bear', 'N/A')}

{memories_str}

Based on this swarm signal, provide a SPECIFIC 0DTE trade recommendation. Be direct and actionable.

Respond with ONLY valid JSON:
{{
  "action": "BUY" or "SELL" or "WAIT",
  "instrument": "e.g. SPX 5820C 0DTE",
  "entry_price_est": <float or null>,
  "target_price": <float or null>,
  "stop_price": <float or null>,
  "max_risk_per_contract": <float or null>,
  "rationale": "<2-3 sentences synthesizing the key thesis>",
  "key_risk": "<what would invalidate this trade>",
  "time_window": "e.g. next 1-2 hours"
}}"""

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=400,
            )
            content = response.choices[0].message.content.strip()
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                trade_data = json.loads(json_match.group())
            else:
                trade_data = json.loads(content)

            return {
                "timestamp": datetime.now().isoformat(),
                "direction": consensus["direction"],
                "confidence": consensus["confidence"],
                "agreement_pct": consensus["agreement_pct"],
                "contrarian_alert": consensus.get("contrarian_alert", False),
                "herding_warning": consensus.get("herding_detected", False),
                "action": trade_data.get("action", "WAIT"),
                "instrument": trade_data.get("instrument", "N/A"),
                "entry_price_est": trade_data.get("entry_price_est"),
                "target_price": trade_data.get("target_price"),
                "stop_price": trade_data.get("stop_price"),
                "max_risk_per_contract": trade_data.get("max_risk_per_contract"),
                "rationale": trade_data.get("rationale", ""),
                "key_risk": trade_data.get("key_risk", ""),
                "time_window": trade_data.get("time_window", ""),
                "bull_case": consensus.get("strongest_bull", ""),
                "bear_case": consensus.get("strongest_bear", ""),
                "market_regime": market_context.get("market_regime", ""),
                "spx_price": market_context.get("spx_price", 0),
                "vix_level": market_context.get("vix_level", 0),
            }
        except Exception as e:
            return {
                "timestamp": datetime.now().isoformat(),
                "direction": consensus["direction"],
                "confidence": consensus["confidence"],
                "action": "WAIT",
                "instrument": "N/A",
                "rationale": f"Report generation failed: {str(e)[:100]}",
                "error": str(e),
            }
