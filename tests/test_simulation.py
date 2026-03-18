import pytest
from swarmspx.simulation.consensus import ConsensusExtractor
from swarmspx.agents.base import AgentVote

def test_consensus_majority_bull():
    votes = [
        AgentVote("a1", "BULL", 80, "reason", "BUY 5820C"),
        AgentVote("a2", "BULL", 75, "reason", "BUY 5820C"),
        AgentVote("a3", "BULL", 90, "reason", "BUY 5820C"),
        AgentVote("a4", "BEAR", 60, "reason", "WAIT"),
        AgentVote("a5", "NEUTRAL", 50, "reason", "WAIT"),
    ]
    extractor = ConsensusExtractor()
    result = extractor.extract(votes)
    assert result["direction"] == "BULL"
    assert result["agreement_pct"] == 60.0
    assert result["confidence"] > 0

def test_consensus_detects_herding():
    votes_r1 = [AgentVote("a1", "BEAR", 70, "r", "w")] * 5
    votes_r2 = [AgentVote("a1", "BULL", 80, "r", "w")] * 5  # all flipped
    extractor = ConsensusExtractor()
    herding = extractor.detect_herding(votes_r1, votes_r2)
    assert herding is True

def test_consensus_extracts_trade_setup():
    votes = [AgentVote(f"a{i}", "BULL", 80, "bullish", "BUY SPX 5820C 0DTE") for i in range(18)]
    votes += [AgentVote(f"a{i+18}", "BEAR", 60, "bearish", "WAIT") for i in range(6)]
    extractor = ConsensusExtractor()
    result = extractor.extract(votes)
    assert "trade_setup" in result
    assert result["trade_setup"]["direction"] == "BULL"
