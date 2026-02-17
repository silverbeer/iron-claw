"""Scraping session state tracker."""

from __future__ import annotations

import time

from pydantic import BaseModel, Field

from models.match_data import MatchData
from radius.models import AccountingUpdate, SessionGrant


class ScrapingSession(BaseModel):
    """Tracks the state of a scraping session including token consumption."""

    session_id: str
    username: str
    grant: SessionGrant
    start_time: float = Field(default_factory=time.time)
    tokens_used: int = 0
    pages_visited: int = 0
    llm_calls_made: int = 0
    tool_calls_made: int = 0
    matches: list[MatchData] = Field(default_factory=list)

    @property
    def matches_found(self) -> int:
        return len(self.matches)

    @property
    def elapsed_seconds(self) -> int:
        return int(time.time() - self.start_time)

    @property
    def budget_percentage(self) -> float:
        """Current token consumption as a percentage of the session budget."""
        if self.grant.token_budget <= 0:
            return 100.0
        return (self.tokens_used / self.grant.token_budget) * 100.0

    @property
    def pages_remaining(self) -> int:
        return max(0, self.grant.max_pages - self.pages_visited)

    @property
    def llm_calls_remaining(self) -> int:
        return max(0, self.grant.max_llm_calls - self.llm_calls_made)

    @property
    def tokens_remaining(self) -> int:
        return max(0, self.grant.token_budget - self.tokens_used)

    def add_tokens(self, count: int) -> None:
        self.tokens_used += count

    def add_page(self) -> None:
        self.pages_visited += 1

    def add_llm_call(self) -> None:
        self.llm_calls_made += 1

    def add_llm_calls(self, count: int) -> None:
        self.llm_calls_made += count

    def add_tool_calls(self, count: int) -> None:
        self.tool_calls_made += count

    def add_match(self, match: MatchData) -> None:
        self.matches.append(match)

    def to_accounting_update(self) -> AccountingUpdate:
        """Convert current session state to an accounting update."""
        return AccountingUpdate(
            tokens_used=self.tokens_used,
            pages_visited=self.pages_visited,
            llm_calls_made=self.llm_calls_made,
            tool_calls_made=self.tool_calls_made,
            matches_found=self.matches_found,
            session_time=self.elapsed_seconds,
        )
