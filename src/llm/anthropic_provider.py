"""Anthropic Claude LLM provider for match extraction."""

from __future__ import annotations

import json

import anthropic
import structlog

from llm.protocol import TokenUsage

logger = structlog.get_logger()

EXTRACTION_PROMPT = """\
You are a structured data extractor. Given HTML from an MLS Next match page,
extract all match information into a JSON array.

Each match object should have these fields:
- home_team: string
- away_team: string
- home_score: integer or null (if not played yet)
- away_score: integer or null (if not played yet)
- date: string (ISO 8601 date, e.g. "2026-03-15")
- time: string or null (e.g. "7:00 PM ET")
- venue: string or null
- competition: string (e.g. "MLS Next")
- status: string ("scheduled", "in_progress", "final")

Return ONLY a JSON array. No markdown, no explanation.
If no matches are found, return an empty array: []
"""


class AnthropicProvider:
    """Claude API implementation of the LLM provider protocol."""

    def __init__(self, model: str = "claude-haiku-4-5") -> None:
        self._model = model
        self._client = anthropic.Anthropic()

    @property
    def model_name(self) -> str:
        return self._model

    def extract_matches(self, html: str) -> tuple[list[dict], TokenUsage]:
        """Send HTML to Claude and parse the structured match response."""
        # Truncate very large HTML to stay within context limits
        max_chars = 100_000
        if len(html) > max_chars:
            html = html[:max_chars]
            logger.warning("llm.html_truncated", original_length=len(html), max_chars=max_chars)

        logger.info("llm.extract.start", model=self._model, html_length=len(html))

        response = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": f"{EXTRACTION_PROMPT}\n\n<html>\n{html}\n</html>",
                }
            ],
        )

        usage = TokenUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            total_tokens=response.usage.input_tokens + response.usage.output_tokens,
            model=self._model,
        )

        # Parse the response text as JSON
        text = response.content[0].text.strip()
        try:
            matches = json.loads(text)
        except json.JSONDecodeError:
            logger.error("llm.extract.parse_error", response_text=text[:200])
            matches = []

        logger.info(
            "llm.extract.complete",
            matches_found=len(matches),
            tokens_used=usage.total_tokens,
        )
        return matches, usage
