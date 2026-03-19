import asyncio
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Optional
from swarmspx.agents.base import AgentVote


@dataclass
class Event:
    """Base event class."""
    event_type: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["event_type"] = self.event_type
        return d


@dataclass
class CycleStarted(Event):
    event_type: str = "cycle_started"
    cycle_id: int = 0


@dataclass
class MarketDataFetched(Event):
    event_type: str = "market_data_fetched"
    market_context: dict = field(default_factory=dict)


@dataclass
class RoundStarted(Event):
    event_type: str = "round_started"
    round_num: int = 0
    total_rounds: int = 5


@dataclass
class AgentVoted(Event):
    event_type: str = "agent_voted"
    agent_id: str = ""
    agent_name: str = ""
    tribe: str = ""
    direction: str = ""
    conviction: int = 0
    reasoning: str = ""
    trade_idea: str = ""
    changed_from: Optional[str] = None
    round_num: int = 0


@dataclass
class RoundCompleted(Event):
    event_type: str = "round_completed"
    round_num: int = 0
    votes: list = field(default_factory=list)
    vote_counts: dict = field(default_factory=dict)


@dataclass
class ConsensusReached(Event):
    event_type: str = "consensus_reached"
    consensus: dict = field(default_factory=dict)


@dataclass
class TradeCardGenerated(Event):
    event_type: str = "trade_card_generated"
    trade_card: dict = field(default_factory=dict)


@dataclass
class CycleCompleted(Event):
    event_type: str = "cycle_completed"
    cycle_id: int = 0
    duration_sec: float = 0.0


@dataclass
class OutcomeResolved(Event):
    event_type: str = "outcome_resolved"
    signal_id: int = 0
    direction: str = ""
    outcome: str = ""
    outcome_pct: float = 0.0


@dataclass
class EngineError(Event):
    event_type: str = "engine_error"
    message: str = ""


class EventBus:
    """Async pub-sub event bus for decoupling engine from UI."""

    def __init__(self):
        self._subscribers: list[asyncio.Queue] = []
        self._callbacks: list[Callable] = []

    def subscribe(self) -> asyncio.Queue:
        """Subscribe and get a queue of events."""
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        """Remove a subscriber queue."""
        if q in self._subscribers:
            self._subscribers.remove(q)

    def on_event(self, callback: Callable):
        """Register a sync callback for events."""
        self._callbacks.append(callback)

    async def emit(self, event: Event):
        """Publish an event to all subscribers."""
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Drop oldest event for slow subscribers
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass
        for cb in self._callbacks:
            try:
                cb(event)
            except Exception:
                pass


class NoOpBus(EventBus):
    """No-op bus for when no UI is attached."""
    async def emit(self, event: Event):
        pass
