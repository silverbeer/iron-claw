"""Unit tests for ScrapingSession state tracking."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from models.match_data import MatchData
from models.session import ScrapingSession
from radius.models import SessionGrant


def _make_session(**kwargs) -> ScrapingSession:
    """Create a ScrapingSession with defaults."""
    grant = SessionGrant(token_budget=10000, max_pages=10, max_llm_calls=50)
    return ScrapingSession(
        session_id="test123",
        username="test-user",
        grant=grant,
        **kwargs,
    )


class TestScrapingSession:
    def test_initial_budget_percentage(self):
        session = _make_session()
        assert session.budget_percentage == 0.0

    def test_budget_percentage_after_tokens(self):
        session = _make_session()
        session.add_tokens(5000)
        assert session.budget_percentage == 50.0

    def test_budget_percentage_exceeds_100(self):
        session = _make_session()
        session.add_tokens(15000)
        assert session.budget_percentage == 150.0

    def test_pages_remaining(self):
        session = _make_session()
        assert session.pages_remaining == 10
        session.add_page()
        session.add_page()
        assert session.pages_remaining == 8

    def test_llm_calls_remaining(self):
        session = _make_session()
        assert session.llm_calls_remaining == 50
        session.add_llm_call()
        assert session.llm_calls_remaining == 49

    def test_matches_found(self):
        session = _make_session()
        assert session.matches_found == 0
        session.add_match(MatchData(home_team="A", away_team="B", date="2026-01-01"))
        assert session.matches_found == 1

    def test_to_accounting_update(self):
        session = _make_session()
        session.add_tokens(3000)
        session.add_page()
        session.add_llm_call()
        session.add_match(MatchData(home_team="A", away_team="B", date="2026-01-01"))

        update = session.to_accounting_update()
        assert update.tokens_used == 3000
        assert update.pages_visited == 1
        assert update.llm_calls_made == 1
        assert update.matches_found == 1
