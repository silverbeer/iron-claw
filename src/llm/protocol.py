"""Token usage model — kept for RADIUS accounting compatibility."""

from __future__ import annotations

from pydantic import BaseModel


class TokenUsage(BaseModel):
    """Token consumption from a single LLM call."""

    input_tokens: int
    output_tokens: int
    total_tokens: int
    model: str
