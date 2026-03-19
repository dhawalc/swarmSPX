import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from swarmspx.agents.base import TraderAgent, AgentVote
from swarmspx.agents.forge import AgentForge

def test_agent_vote_has_required_fields():
    vote = AgentVote(
        agent_id="test_agent",
        direction="BULL",
        conviction=75,
        reasoning="Test reasoning",
        trade_idea="BUY 5820C"
    )
    assert vote.direction in ["BULL", "BEAR", "NEUTRAL"]
    assert 0 <= vote.conviction <= 100

@pytest.mark.asyncio
async def test_agent_thinks_and_returns_vote():
    with patch("openai.AsyncOpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"direction":"BULL","conviction":70,"reasoning":"test","trade_idea":"BUY 5820C"}'))]
        ))
        agent = TraderAgent(
            agent_id="vwap_victor",
            name="VWAP Victor",
            persona="You trade VWAP.",
            specialty="price_action",
            bias="neutral"
        )
        market_context = {"spx_price": 5800.0, "vix_level": 14.5, "market_regime": "low_vol_grind"}
        vote = await agent.think(market_context, round_num=1, peers_votes=[])
        assert vote.direction in ["BULL", "BEAR", "NEUTRAL"]
        assert 0 <= vote.conviction <= 100

@pytest.mark.asyncio
async def test_claude_cli_agent_thinks():
    with patch("swarmspx.claude_client.claude_chat", new_callable=AsyncMock) as mock_claude:
        mock_claude.return_value = '{"direction":"BEAR","conviction":85,"reasoning":"VIX elevated","trade_idea":"BUY SPX 5790P 0DTE"}'
        agent = TraderAgent(
            agent_id="risk_rick",
            name="Risk Rick",
            persona="You manage risk.",
            specialty="risk_mgmt",
            bias="conservative",
            use_claude_cli=True,
            claude_model="sonnet",
        )
        market_context = {"spx_price": 5800.0, "vix_level": 22.5, "market_regime": "elevated_vol"}
        vote = await agent.think(market_context, round_num=1, peers_votes=[])
        assert vote.direction == "BEAR"
        assert vote.conviction == 85
        mock_claude.assert_called_once()

def test_forge_creates_all_24_agents():
    forge = AgentForge("config/agents.yaml")
    agents = forge.create_all()
    assert len(agents) == 24
    ids = [a.agent_id for a in agents]
    assert "vwap_victor" in ids
    assert "synthesis_syd" in ids

def test_forge_assigns_premium_local_to_strategists():
    """Strategists use phi4:14b locally (058932c switched from Claude CLI)."""
    forge = AgentForge("config/agents.yaml")
    agents = forge.create_all()
    strategists = [a for a in agents if a.tribe == "strategists"]
    assert len(strategists) == 6
    assert all(a.use_claude_cli is False for a in strategists)
    assert all(a.model == "phi4:14b" for a in strategists)
    # Others should use Ollama with llama3.1:8b
    others = [a for a in agents if a.tribe != "strategists"]
    assert len(others) == 18
    assert all(a.use_claude_cli is False for a in others)
    assert all(a.model == "llama3.1:8b" for a in others)
