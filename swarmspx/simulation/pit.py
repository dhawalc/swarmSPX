import asyncio
from collections import Counter
from typing import Optional
from swarmspx.agents.base import TraderAgent, AgentVote
from swarmspx.simulation.consensus import ConsensusExtractor
from swarmspx.memory import AOMemory
from swarmspx.events import EventBus, NoOpBus, RoundStarted, AgentVoted, RoundCompleted

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
        bus: Optional[EventBus] = None,
    ):
        self.agents = agents
        self.memory = memory
        self.num_rounds = num_rounds
        self.consensus_extractor = ConsensusExtractor()
        self.bus = bus or NoOpBus()

    async def run(self, market_context: dict, agent_weights: Optional[dict[str, float]] = None) -> dict:
        """Run a full simulation cycle and return consensus.

        Args:
            market_context: Current market snapshot.
            agent_weights: Optional ELO-derived weights for weighted consensus.
        """
        all_rounds: list[list[AgentVote]] = []
        current_votes: list[AgentVote] = []

        for round_num in range(1, self.num_rounds + 1):
            await self.bus.emit(RoundStarted(round_num=round_num, total_rounds=self.num_rounds))
            prior_votes = current_votes.copy()
            current_votes = await self._run_round(
                market_context, round_num, prior_votes
            )
            all_rounds.append(current_votes)
            vote_counts = dict(Counter(v.direction for v in current_votes))
            await self.bus.emit(RoundCompleted(
                round_num=round_num,
                votes=[{"agent_id": v.agent_id, "direction": v.direction, "conviction": v.conviction, "trade_idea": v.trade_idea, "changed_from": v.changed_from} for v in current_votes],
                vote_counts=vote_counts,
            ))

        # Final consensus from last round (with optional performance weights)
        prior = all_rounds[-2] if len(all_rounds) >= 2 else None
        consensus = self.consensus_extractor.extract(current_votes, prior, agent_weights=agent_weights)

        # Add round-by-round drift analysis
        consensus["rounds"] = len(all_rounds)
        consensus["round_directions"] = [
            Counter(v.direction for v in r).most_common(1)[0][0]
            for r in all_rounds
        ]

        # Include individual votes for Darwinian scoring storage
        consensus["individual_votes"] = [
            {"agent_id": v.agent_id, "direction": v.direction, "conviction": v.conviction}
            for v in current_votes
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
            # Memory recalls are async — fetch in parallel before dispatching
            # agent thinking (review #6: was blocking the event loop).
            # recall_for_agent fail-softs to "" so we don't need return_exceptions.
            regime = market_context.get("market_regime", "")
            memory_contexts = await asyncio.gather(*[
                self.memory.recall_for_agent(
                    agent_id=agent.agent_id,
                    specialty=agent.specialty,
                    market_context=regime,
                )
                for agent in batch
            ])
            tasks = [
                agent.think(market_context, round_num, prior_votes, memory_contexts[j])
                for j, agent in enumerate(batch)
            ]
            batch_votes = await asyncio.gather(*tasks, return_exceptions=True)
            for j, vote in enumerate(batch_votes):
                if isinstance(vote, AgentVote):
                    votes.append(vote)
                    agent = batch[j]
                    await self.bus.emit(AgentVoted(
                        agent_id=vote.agent_id,
                        agent_name=agent.name,
                        tribe=agent.tribe,
                        direction=vote.direction,
                        conviction=vote.conviction,
                        reasoning=vote.reasoning,
                        trade_idea=vote.trade_idea,
                        changed_from=vote.changed_from,
                        round_num=round_num,
                    ))

        return votes
