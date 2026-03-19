import json
import re
from dataclasses import dataclass, field
from typing import Optional
from openai import AsyncOpenAI

@dataclass
class AgentVote:
    agent_id: str
    direction: str          # "BULL" | "BEAR" | "NEUTRAL"
    conviction: int         # 0-100
    reasoning: str
    trade_idea: str
    changed_from: Optional[str] = None  # if they flipped from prior round

class TraderAgent:
    """A single trader-agent persona in the swarm."""

    def __init__(
        self,
        agent_id: str,
        name: str,
        persona: str,
        specialty: str,
        bias: str,
        ollama_base_url: str = "http://localhost:11434/v1",
        model: str = "llama3.1:8b",
        tribe: str = "unknown",
        api_key: str = "ollama",
        use_claude_cli: bool = False,
        claude_model: str = "sonnet",
    ):
        self.agent_id = agent_id
        self.name = name
        self.persona = persona
        self.specialty = specialty
        self.bias = bias
        self.model = model
        self.tribe = tribe
        self.use_claude_cli = use_claude_cli
        self.claude_model = claude_model
        if not use_claude_cli:
            self.client = AsyncOpenAI(base_url=ollama_base_url, api_key=api_key)
        else:
            self.client = None
        self.last_vote: Optional[AgentVote] = None

    def _build_prompt(
        self,
        market_context: dict,
        round_num: int,
        peers_votes: list[AgentVote],
        memory_context: str = ""
    ) -> str:
        market_str = f"""
Current SPX: ${market_context.get('spx_price', 0):.2f}
SPX Change: {market_context.get('spx_change_pct', 0):+.2f}%
SPX vs VWAP: {market_context.get('spx_vwap_distance_pct', 0):+.2f}%
VIX: {market_context.get('vix_level', 0):.1f} ({market_context.get('vix_change', 0):+.2f})
Put/Call Ratio: {market_context.get('put_call_ratio', 1.0):.2f}
Regime: {market_context.get('market_regime', 'unknown')}
""".strip()

        # Options chain data (only if Tradier is configured)
        options_str = ""
        if market_context.get("options_chain"):
            atm_strike = market_context.get("atm_strike", 0)
            atm_iv = market_context.get("atm_iv", 0)
            chain = market_context["options_chain"]
            calls = [c for c in chain if c["type"] == "call"]
            puts = [c for c in chain if c["type"] == "put"]
            lines = [
                f"\nOPTIONS DATA:",
                f"ATM Strike: {atm_strike:.0f} | ATM IV: {atm_iv:.1f}%",
                f"Put/Call Ratio: {market_context.get('put_call_ratio', 1.0):.2f} (from live chain)",
            ]
            for c in calls[:3]:
                lines.append(
                    f"  {c['strike']:.0f}C bid/ask ${c['bid']:.2f}/${c['ask']:.2f} "
                    f"delta={c['delta']:.2f} IV={c['iv']:.1f}%"
                )
            for p in puts[:3]:
                lines.append(
                    f"  {p['strike']:.0f}P bid/ask ${p['bid']:.2f}/${p['ask']:.2f} "
                    f"delta={p['delta']:.2f} IV={p['iv']:.1f}%"
                )
            options_str = "\n".join(lines)

        peers_str = ""
        if peers_votes and round_num > 1:
            vote_counts = {"BULL": 0, "BEAR": 0, "NEUTRAL": 0}
            for v in peers_votes:
                vote_counts[v.direction] = vote_counts.get(v.direction, 0) + 1
            peers_str = f"\nOther traders' current positions: {vote_counts['BULL']} BULL, {vote_counts['BEAR']} BEAR, {vote_counts['NEUTRAL']} NEUTRAL\n"
            if round_num > 1:
                bulls = [v for v in peers_votes if v.direction == "BULL"]
                bears = [v for v in peers_votes if v.direction == "BEAR"]
                if bulls:
                    top_bull = max(bulls, key=lambda v: v.conviction)
                    peers_str += f"Strongest bull: {top_bull.agent_id} ({top_bull.conviction}%): {top_bull.reasoning[:150]}\n"
                if bears:
                    top_bear = max(bears, key=lambda v: v.conviction)
                    peers_str += f"Strongest bear: {top_bear.agent_id} ({top_bear.conviction}%): {top_bear.reasoning[:150]}\n"

        prior_str = ""
        if self.last_vote and round_num > 1:
            prior_str = f"\nYour position in round {round_num-1}: {self.last_vote.direction} at {self.last_vote.conviction}% conviction.\n"

        prompt = f"""{self.persona}

MARKET DATA (Round {round_num}):
{market_str}
{options_str}
{peers_str}
{prior_str}
{memory_context}

Based on your expertise in {self.specialty}, analyze the current market and give your trading signal.
You are trading SPX 0DTE options.

Respond with ONLY valid JSON, no other text:
{{
  "direction": "BULL" or "BEAR" or "NEUTRAL",
  "conviction": <integer 0-100>,
  "reasoning": "<2-3 sentences explaining your view based on your specialty>",
  "trade_idea": "<specific trade: e.g. BUY SPX 5820C 0DTE or SELL SPX 5790P 0DTE or WAIT>"
}}"""
        return prompt

    async def think(
        self,
        market_context: dict,
        round_num: int,
        peers_votes: list[AgentVote],
        memory_context: str = ""
    ) -> AgentVote:
        """Analyze market and produce a vote."""
        prompt = self._build_prompt(market_context, round_num, peers_votes, memory_context)
        try:
            if self.use_claude_cli:
                content = await self._think_claude(prompt)
            else:
                content = await self._think_openai(prompt)

            # Parse JSON from response
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
            else:
                data = json.loads(content)

            direction = data.get("direction", "NEUTRAL").upper()
            if direction not in ("BULL", "BEAR", "NEUTRAL"):
                direction = "NEUTRAL"
            conviction = max(0, min(100, int(data.get("conviction", 50))))

            vote = AgentVote(
                agent_id=self.agent_id,
                direction=direction,
                conviction=conviction,
                reasoning=data.get("reasoning", "No reasoning provided"),
                trade_idea=data.get("trade_idea", "WAIT"),
                changed_from=self.last_vote.direction if self.last_vote and self.last_vote.direction != direction else None
            )
            self.last_vote = vote
            return vote

        except Exception as e:
            vote = AgentVote(
                agent_id=self.agent_id,
                direction="NEUTRAL",
                conviction=50,
                reasoning=f"Analysis unavailable: {str(e)[:100]}",
                trade_idea="WAIT"
            )
            self.last_vote = vote
            return vote

    async def _think_openai(self, prompt: str) -> str:
        """Get response via OpenAI-compatible API (Ollama)."""
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=300,
        )
        return response.choices[0].message.content.strip()

    async def _think_claude(self, prompt: str) -> str:
        """Get response via Claude CLI subprocess (Max plan OAuth)."""
        from swarmspx.claude_client import claude_chat
        response = await claude_chat(prompt, model=self.claude_model)
        if not response:
            raise RuntimeError("Claude CLI returned empty response")
        return response
