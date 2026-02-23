"""Provider routing — maps model names to upstream API providers."""

from __future__ import annotations

DOWNGRADE_MODELS: dict[str, str] = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-4o-mini",
}


def resolve_provider(model: str) -> str:
    """Return 'openai' or 'anthropic' based on model name prefix."""
    if model.startswith(("gpt-", "o1-", "o3-", "o4-")):
        return "openai"
    return "anthropic"
