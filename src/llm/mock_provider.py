"""Mock LLM provider for testing without API calls."""

from __future__ import annotations

from llm.protocol import TokenUsage

MOCK_MATCHES = [
    {
        "home_team": "FC Dallas U17",
        "away_team": "Houston Dynamo U17",
        "home_score": 2,
        "away_score": 1,
        "date": "2026-03-15",
        "time": "7:00 PM CT",
        "venue": "Toyota Stadium",
        "competition": "MLS Next",
        "status": "final",
    },
    {
        "home_team": "Austin FC U17",
        "away_team": "Sporting KC U17",
        "home_score": None,
        "away_score": None,
        "date": "2026-03-22",
        "time": "5:00 PM CT",
        "venue": "St. David's Performance Center",
        "competition": "MLS Next",
        "status": "scheduled",
    },
]


class MockProvider:
    """Mock LLM provider that returns canned match data.

    Configurable token burn rate for testing throttling behavior.
    """

    def __init__(
        self,
        model: str = "mock-model",
        tokens_per_call: int = 500,
        matches_per_call: int = 2,
    ) -> None:
        self._model = model
        self._tokens_per_call = tokens_per_call
        self._matches_per_call = matches_per_call

    @property
    def model_name(self) -> str:
        return self._model

    def extract_matches(self, html: str) -> tuple[list[dict], TokenUsage]:
        """Return mock matches and simulated token usage."""
        usage = TokenUsage(
            input_tokens=self._tokens_per_call * 3 // 4,
            output_tokens=self._tokens_per_call // 4,
            total_tokens=self._tokens_per_call,
            model=self._model,
        )
        return MOCK_MATCHES[: self._matches_per_call], usage
