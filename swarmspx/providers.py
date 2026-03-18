"""Model provider resolution for hybrid local/cloud routing."""
import os
from typing import Optional


def resolve_model(model_key: str, settings: dict) -> tuple[str, str, str]:
    """Resolve a model key to (base_url, api_key, model_name).

    Looks up settings["models"][model_key] and its provider.
    Falls back to settings["ollama"] if new config structure is missing.
    """
    models = settings.get("models")
    providers = settings.get("providers")

    if models and model_key in models and providers:
        model_def = models[model_key]
        provider_name = model_def["provider"]
        provider = providers[provider_name]
        base_url = provider["base_url"]

        # Resolve API key: direct value or env var
        if "api_key_env" in provider:
            api_key = os.environ.get(provider["api_key_env"], "")
            if not api_key:
                raise ValueError(
                    f"Environment variable {provider['api_key_env']} not set "
                    f"(required for provider '{provider_name}')"
                )
        else:
            api_key = provider.get("api_key", "ollama")

        return base_url, api_key, model_def["model"]

    # Backward compat: fall back to flat ollama config
    ollama = settings.get("ollama", {})
    return (
        ollama.get("base_url", "http://localhost:11434/v1"),
        ollama.get("api_key", "ollama"),
        ollama.get("agent_model", "llama3.1:8b"),
    )


def resolve_tribe_model(tribe_name: str, settings: dict) -> tuple[str, str, str]:
    """Resolve the model for a specific tribe."""
    tribe_models = settings.get("tribe_models", {})
    model_key = tribe_models.get(tribe_name, "fast_local")
    return resolve_model(model_key, settings)


def resolve_synthesis_model(settings: dict) -> tuple[str, str, str]:
    """Resolve the synthesis model."""
    model_key = settings.get("synthesis_model", "fast_local")
    if isinstance(model_key, str) and settings.get("models"):
        return resolve_model(model_key, settings)
    # Backward compat
    ollama = settings.get("ollama", {})
    return (
        ollama.get("base_url", "http://localhost:11434/v1"),
        ollama.get("api_key", "ollama"),
        ollama.get("synthesis_model", "phi4:14b"),
    )
