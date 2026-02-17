"""Proxy session state tracker — mirrors ScrapingSession for LLM proxy use."""

from __future__ import annotations

import time

from pydantic import BaseModel, Field

from radius.models import AccountingUpdate, SessionGrant


class ProxySession(BaseModel):
    """Tracks token consumption and LLM calls across the proxy lifecycle."""

    session_id: str
    username: str
    grant: SessionGrant
    start_time: float = Field(default_factory=time.time)
    tokens_used: int = 0
    llm_calls_made: int = 0

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
    def tokens_remaining(self) -> int:
        return max(0, self.grant.token_budget - self.tokens_used)

    @property
    def llm_calls_remaining(self) -> int:
        return max(0, self.grant.max_llm_calls - self.llm_calls_made)

    def record_usage(self, input_tokens: int, output_tokens: int) -> None:
        """Record token usage from a single API call."""
        self.tokens_used += input_tokens + output_tokens
        self.llm_calls_made += 1

    def to_accounting_update(self) -> AccountingUpdate:
        """Convert current session state to an accounting update."""
        return AccountingUpdate(
            tokens_used=self.tokens_used,
            llm_calls_made=self.llm_calls_made,
            session_time=self.elapsed_seconds,
        )
