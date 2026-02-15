"""Unit tests for the mock LLM provider."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from llm.mock_provider import MockProvider


class TestMockProvider:
    def test_returns_matches(self):
        provider = MockProvider()
        matches, _usage = provider.extract_matches("<html>test</html>")
        assert len(matches) == 2
        assert matches[0]["home_team"] == "FC Dallas U17"

    def test_returns_token_usage(self):
        provider = MockProvider(tokens_per_call=1000)
        _, usage = provider.extract_matches("<html>test</html>")
        assert usage.total_tokens == 1000
        assert usage.input_tokens == 750
        assert usage.output_tokens == 250

    def test_model_name(self):
        provider = MockProvider(model="test-model")
        assert provider.model_name == "test-model"

    def test_configurable_matches_per_call(self):
        provider = MockProvider(matches_per_call=1)
        matches, _ = provider.extract_matches("<html></html>")
        assert len(matches) == 1
