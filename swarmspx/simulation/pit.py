import asyncio
from collections import Counter
from typing import Optional
from swarmspx.agents.base import TraderAgent, AgentVote
from swarmspx.simulation.consensus import ConsensusExtractor
from swarmspx.memory import AOMemory

BATCH_SIZE = 6  # Run 6 agents in parallel at a time

class TradingPit:
    """
    The core simulation engine.
    Runs N rounds of agent deliberation and extracts consensus.
    """

    def __init__(
        self,
        agents: list[TraderAgent],
        memory: AOMemory,
        num_rounds: int = 5,
    ):
        self.agents = agents
        self.memory = memory
        self.num_rounds = num_rounds
        self.consensus_extractor = ConsensusExtractor()

    async def run(self, market_context: dict) -> dict:
        """Run a full simulation cycle and return consensus."""
        all_rounds: list[list[AgentVote]] = []
        current_votes: list[AgentVote] = []

        for round_num in range(1, self.num_rounds + 1):
            prior_votes = current_votes.copy()
            current_votes = await self._run_round(
                market_context, round_num, prior_votes
            )
            all_rounds.append(current_votes)

        # Final consensus from last round
        prior = all_rounds[-2] if len(all_rounds) >= 2 else None
        consensus = self.consensus_extractor.extract(current_votes, prior)

        # Add round-by-round drift analysis
        consensus["rounds"] = len(all_rounds)
        consensus["round_directions"] = [
            Counter(v.direction for v in r).most_common(1)[0][0]
            for r in all_rounds
        ]

        return consensus

    async def _run_round(
        self,
        market_context: dict,
        round_num: int,
        prior_votes: list[AgentVote],
    ) -> list[AgentVote]:
        """Run one round: all agents think in parallel batches."""
        votes: list[AgentVote] = []

        for i in range(0, len(self.agents), BATCH_SIZE):
            batch = self.agents[i:i + BATCH_SIZE]
            tasks = []
            for agent in batch:
                # Get AOMS memory context relevant to this agent's specialty
                memory_context = self.memory.recall_for_agent(
                    agent_id=agent.agent_id,
                    specialty=agent.specialty,
                    market_context=market_context.get("market_regime", "")
                )
                tasks.append(agent.think(market_context, round_num, prior_votes, memory_context))
            batch_votes = await asyncio.gather(*tasks, return_exceptions=True)
            for vote in batch_votes:
                if isinstance(vote, AgentVote):
                    votes.append(vote)

        return votes
