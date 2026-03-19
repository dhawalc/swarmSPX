"""Tests for custom agent loading, merging, and management."""

import os
import tempfile

import pytest
import yaml

from swarmspx.agents.forge import AgentForge, MAX_TOTAL_AGENTS


@pytest.fixture
def custom_yaml(tmp_path):
    """Create a temporary custom_agents.yaml with two sample agents."""
    custom = tmp_path / "custom_agents.yaml"
    custom.write_text(
        yaml.safe_dump(
            {
                "agents": [
                    {
                        "id": "elliott_emma",
                        "name": "Elliott Emma",
                        "tribe": "technical",
                        "specialty": "elliott_wave",
                        "bias": "wave_counter",
                        "persona": "You count Elliott Waves.",
                    },
                    {
                        "id": "crypto_chris",
                        "name": "Crypto Chris",
                        "tribe": "macro",
                        "specialty": "crypto_correlation",
                        "bias": "risk_on_proxy",
                        "persona": "You track BTC as a risk proxy.",
                    },
                ]
            }
        )
    )
    return str(custom)


@pytest.fixture
def empty_custom_yaml(tmp_path):
    """Create a temporary empty custom_agents.yaml."""
    custom = tmp_path / "custom_agents.yaml"
    custom.write_text(yaml.safe_dump({"agents": []}))
    return str(custom)


def _make_forge(custom_path: str) -> AgentForge:
    return AgentForge(
        config_path="config/agents.yaml",
        settings_path="config/settings.yaml",
        custom_path=custom_path,
    )


def test_forge_loads_custom_agents(custom_yaml):
    """Custom agents from YAML appear in get_custom_agents()."""
    forge = _make_forge(custom_yaml)
    custom = forge.get_custom_agents()
    assert len(custom) == 2
    ids = {a["id"] for a in custom}
    assert "elliott_emma" in ids
    assert "crypto_chris" in ids


def test_custom_agent_gets_default_model(custom_yaml):
    """Custom agent with an unknown tribe falls back to fast_local."""
    # Write a custom agent with a tribe not in tribe_models
    with open(custom_yaml, "w") as f:
        yaml.safe_dump(
            {
                "agents": [
                    {
                        "id": "alien_al",
                        "name": "Alien Al",
                        "tribe": "extraterrestrial",  # not in settings
                        "specialty": "ufo_sightings",
                        "bias": "contrarian",
                        "persona": "You trade based on alien signals.",
                    }
                ]
            },
            f,
        )
    forge = _make_forge(custom_yaml)
    agents = forge.create_all()

    alien = next(a for a in agents if a.agent_id == "alien_al")
    # Should get fast_local fallback (llama3.1:8b)
    assert alien.model == "llama3.1:8b"
    assert alien.tribe == "extraterrestrial"


def test_total_count_includes_custom(custom_yaml):
    """create_all() returns base 24 + custom agents."""
    forge = _make_forge(custom_yaml)
    agents = forge.create_all()
    assert len(agents) == 26  # 24 base + 2 custom


def test_create_all_without_custom(empty_custom_yaml):
    """create_all() returns exactly 24 base agents with no custom file."""
    forge = _make_forge(empty_custom_yaml)
    agents = forge.create_all()
    assert len(agents) == 24


def test_create_all_missing_custom_file():
    """create_all() works when custom_agents.yaml doesn't exist."""
    forge = _make_forge("/tmp/nonexistent_custom_agents.yaml")
    agents = forge.create_all()
    assert len(agents) == 24


def test_add_custom_agent(empty_custom_yaml):
    """add_custom_agent() adds an agent and persists to YAML."""
    forge = _make_forge(empty_custom_yaml)

    added = forge.add_custom_agent(
        {
            "id": "test_agent",
            "name": "Test Agent",
            "tribe": "technical",
            "persona": "You are a test.",
            "specialty": "testing",
            "bias": "neutral",
        }
    )
    assert added["id"] == "test_agent"
    assert len(forge.get_custom_agents()) == 1

    # Verify persisted to disk
    with open(empty_custom_yaml) as f:
        data = yaml.safe_load(f)
    assert len(data["agents"]) == 1
    assert data["agents"][0]["id"] == "test_agent"


def test_add_duplicate_agent_rejected(custom_yaml):
    """Adding an agent with an existing id raises ValueError."""
    forge = _make_forge(custom_yaml)
    with pytest.raises(ValueError, match="already exists"):
        forge.add_custom_agent(
            {
                "id": "elliott_emma",  # already in custom_yaml
                "name": "Duplicate",
                "persona": "Dup",
                "specialty": "dup",
                "bias": "dup",
            }
        )


def test_add_base_agent_id_rejected(empty_custom_yaml):
    """Adding an agent with a base agent's id raises ValueError."""
    forge = _make_forge(empty_custom_yaml)
    with pytest.raises(ValueError, match="already exists"):
        forge.add_custom_agent(
            {
                "id": "vwap_victor",  # base agent id
                "name": "Fake Victor",
                "persona": "Fake",
                "specialty": "fake",
                "bias": "fake",
            }
        )


def test_add_agent_missing_field_rejected(empty_custom_yaml):
    """Adding an agent without required fields raises ValueError."""
    forge = _make_forge(empty_custom_yaml)
    with pytest.raises(ValueError, match="'persona'"):
        forge.add_custom_agent(
            {
                "id": "no_persona",
                "name": "No Persona",
                "specialty": "none",
                "bias": "none",
                # missing persona
            }
        )


def test_remove_custom_agent(custom_yaml):
    """remove_custom_agent() removes the agent and persists."""
    forge = _make_forge(custom_yaml)
    assert len(forge.get_custom_agents()) == 2

    removed = forge.remove_custom_agent("elliott_emma")
    assert removed is True
    assert len(forge.get_custom_agents()) == 1

    # Verify persisted
    with open(custom_yaml) as f:
        data = yaml.safe_load(f)
    assert len(data["agents"]) == 1


def test_remove_nonexistent_agent(custom_yaml):
    """remove_custom_agent() returns False for unknown id."""
    forge = _make_forge(custom_yaml)
    assert forge.remove_custom_agent("ghost_agent") is False


def test_agent_cap_enforced(empty_custom_yaml):
    """Cannot exceed MAX_TOTAL_AGENTS via add_custom_agent()."""
    forge = _make_forge(empty_custom_yaml)
    # Base has 24 agents, cap is 30, so we can add 6
    for i in range(6):
        forge.add_custom_agent(
            {
                "id": f"cap_test_{i}",
                "name": f"Cap Test {i}",
                "persona": "Testing cap.",
                "specialty": "cap",
                "bias": "neutral",
            }
        )
    # 7th should fail
    with pytest.raises(ValueError, match="cap reached"):
        forge.add_custom_agent(
            {
                "id": "cap_test_overflow",
                "name": "Overflow",
                "persona": "Too many.",
                "specialty": "cap",
                "bias": "neutral",
            }
        )
