"""LLM provider protocol — model-agnostic interface for match extraction."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class TokenUsage(BaseModel):
    """Token consumption from a single LLM call."""

    input_tokens: int
    output_tokens: int
    total_tokens: int
    model: str


class LLMProvider(Protocol):
    """Protocol for LLM providers that extract match data from HTML."""

    @property
    def model_name(self) -> str:
        """The model identifier being used."""
        ...

    def extract_matches(self, html: str) -> tuple[list[dict], TokenUsage]:
        """Parse HTML content and extract match data.

        Args:
            html: Raw HTML content from a match page.

        Returns:
            Tuple of (list of match data dicts, token usage).
        """
        ...
