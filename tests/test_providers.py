import pytest
from unittest.mock import patch
from swarmspx.providers import resolve_model, resolve_tribe_model, resolve_synthesis_model

SETTINGS = {
    "providers": {
        "ollama": {"base_url": "http://localhost:11434/v1", "api_key": "ollama"},
        "anthropic": {"base_url": "https://api.anthropic.com/v1/", "api_key_env": "ANTHROPIC_API_KEY"},
    },
    "models": {
        "fast_local": {"provider": "ollama", "model": "llama3.1:8b"},
        "sonnet": {"provider": "anthropic", "model": "claude-sonnet-4-6-20250514"},
        "opus": {"provider": "anthropic", "model": "claude-opus-4-0-20250514"},
    },
    "tribe_models": {
        "technical": "fast_local",
        "macro": "fast_local",
        "sentiment": "fast_local",
        "strategists": "sonnet",
    },
    "synthesis_model": "opus",
    "ollama": {"base_url": "http://localhost:11434/v1", "api_key": "ollama", "agent_model": "llama3.1:8b", "synthesis_model": "phi4:14b"},
}


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-123"})
def test_resolve_ollama_model():
    url, key, model = resolve_model("fast_local", SETTINGS)
    assert url == "http://localhost:11434/v1"
    assert key == "ollama"
    assert model == "llama3.1:8b"


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-123"})
def test_resolve_anthropic_model():
    url, key, model = resolve_model("sonnet", SETTINGS)
    assert url == "https://api.anthropic.com/v1/"
    assert key == "sk-test-123"
    assert "claude-sonnet" in model


def test_resolve_anthropic_missing_key_raises():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            resolve_model("sonnet", SETTINGS)


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-123"})
def test_resolve_tribe_model_strategists():
    url, key, model = resolve_tribe_model("strategists", SETTINGS)
    assert "anthropic" in url
    assert "claude" in model


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-123"})
def test_resolve_tribe_model_technical():
    url, key, model = resolve_tribe_model("technical", SETTINGS)
    assert "11434" in url
    assert model == "llama3.1:8b"


def test_backward_compat_no_providers():
    old_settings = {
        "ollama": {"base_url": "http://localhost:11434/v1", "api_key": "ollama", "agent_model": "llama3.1:8b"},
    }
    url, key, model = resolve_model("anything", old_settings)
    assert url == "http://localhost:11434/v1"
    assert model == "llama3.1:8b"


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-123"})
def test_resolve_synthesis_model():
    url, key, model = resolve_synthesis_model(SETTINGS)
    assert "anthropic" in url
    assert "opus" in model
