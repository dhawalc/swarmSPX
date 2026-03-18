import pytest
from unittest.mock import patch
from swarmspx.providers import resolve_model, resolve_tribe_model, resolve_synthesis_model

SETTINGS = {
    "providers": {
        "ollama": {"base_url": "http://localhost:11434/v1", "api_key": "ollama"},
    },
    "models": {
        "fast_local": {"provider": "ollama", "model": "llama3.1:8b"},
        "claude_sonnet": {"provider": "claude_cli", "model": "sonnet"},
        "claude_opus": {"provider": "claude_cli", "model": "opus"},
    },
    "tribe_models": {
        "technical": "fast_local",
        "macro": "fast_local",
        "sentiment": "fast_local",
        "strategists": "claude_sonnet",
    },
    "synthesis_model": "claude_sonnet",
    "ollama": {"base_url": "http://localhost:11434/v1", "api_key": "ollama", "agent_model": "llama3.1:8b", "synthesis_model": "phi4:14b"},
}


def test_resolve_ollama_model():
    cfg = resolve_model("fast_local", SETTINGS)
    assert cfg["base_url"] == "http://localhost:11434/v1"
    assert cfg["api_key"] == "ollama"
    assert cfg["model"] == "llama3.1:8b"
    assert cfg["use_claude_cli"] is False


def test_resolve_claude_cli_model():
    cfg = resolve_model("claude_sonnet", SETTINGS)
    assert cfg["use_claude_cli"] is True
    assert cfg["claude_model"] == "sonnet"
    assert cfg["model"] == "sonnet"


def test_resolve_tribe_model_strategists_uses_claude():
    cfg = resolve_tribe_model("strategists", SETTINGS)
    assert cfg["use_claude_cli"] is True
    assert cfg["claude_model"] == "sonnet"


def test_resolve_tribe_model_technical_uses_ollama():
    cfg = resolve_tribe_model("technical", SETTINGS)
    assert cfg["use_claude_cli"] is False
    assert cfg["model"] == "llama3.1:8b"


def test_backward_compat_no_providers():
    old_settings = {
        "ollama": {"base_url": "http://localhost:11434/v1", "api_key": "ollama", "agent_model": "llama3.1:8b"},
    }
    cfg = resolve_model("anything", old_settings)
    assert cfg["base_url"] == "http://localhost:11434/v1"
    assert cfg["model"] == "llama3.1:8b"
    assert cfg["use_claude_cli"] is False


def test_resolve_synthesis_model_claude():
    cfg = resolve_synthesis_model(SETTINGS)
    assert cfg["use_claude_cli"] is True
    assert cfg["claude_model"] == "sonnet"
