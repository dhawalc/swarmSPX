import pytest
import asyncio
from swarmspx.events import (
    EventBus, NoOpBus, Event,
    CycleStarted, MarketDataFetched, RoundStarted,
    AgentVoted, RoundCompleted, ConsensusReached,
    TradeCardGenerated, CycleCompleted, EngineError,
)


@pytest.mark.asyncio
async def test_event_bus_subscriber_receives_events():
    bus = EventBus()
    q = bus.subscribe()
    await bus.emit(CycleStarted(cycle_id=1))
    event = q.get_nowait()
    assert event.event_type == "cycle_started"
    assert event.cycle_id == 1


@pytest.mark.asyncio
async def test_event_bus_multiple_subscribers():
    bus = EventBus()
    q1 = bus.subscribe()
    q2 = bus.subscribe()
    await bus.emit(RoundStarted(round_num=3, total_rounds=5))
    e1 = q1.get_nowait()
    e2 = q2.get_nowait()
    assert e1.round_num == 3
    assert e2.round_num == 3


@pytest.mark.asyncio
async def test_event_bus_callback():
    bus = EventBus()
    received = []
    bus.on_event(lambda e: received.append(e))
    await bus.emit(EngineError(message="test error"))
    assert len(received) == 1
    assert received[0].message == "test error"


@pytest.mark.asyncio
async def test_noop_bus_does_nothing():
    bus = NoOpBus()
    # Should not raise
    await bus.emit(CycleStarted(cycle_id=99))


def test_event_to_dict():
    event = AgentVoted(
        agent_id="vwap_victor",
        agent_name="VWAP Victor",
        tribe="technical",
        direction="BULL",
        conviction=80,
        reasoning="test",
        trade_idea="BUY 5820C",
        round_num=1,
    )
    d = event.to_dict()
    assert d["event_type"] == "agent_voted"
    assert d["agent_id"] == "vwap_victor"
    assert d["tribe"] == "technical"
    assert d["conviction"] == 80


@pytest.mark.asyncio
async def test_event_bus_unsubscribe():
    bus = EventBus()
    q = bus.subscribe()
    bus.unsubscribe(q)
    await bus.emit(CycleStarted(cycle_id=1))
    assert q.empty()


@pytest.mark.asyncio
async def test_full_event_flow():
    """Verify all event types can be emitted and received."""
    bus = EventBus()
    q = bus.subscribe()
    events = [
        CycleStarted(cycle_id=1),
        MarketDataFetched(market_context={"spx_price": 5800.0}),
        RoundStarted(round_num=1, total_rounds=5),
        AgentVoted(agent_id="test", direction="BULL", conviction=70, round_num=1),
        RoundCompleted(round_num=1, votes=[], vote_counts={"BULL": 15}),
        ConsensusReached(consensus={"direction": "BULL"}),
        TradeCardGenerated(trade_card={"action": "BUY"}),
        CycleCompleted(cycle_id=1, duration_sec=42.5),
    ]
    for e in events:
        await bus.emit(e)
    assert q.qsize() == len(events)
    for expected in events:
        received = q.get_nowait()
        assert received.event_type == expected.event_type
