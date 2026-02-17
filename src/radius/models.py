"""Pydantic models for RADIUS configuration and session data."""

from __future__ import annotations

from pydantic import BaseModel
from pydantic_settings import BaseSettings


class RadiusConfig(BaseSettings):
    """RADIUS server connection settings."""

    model_config = {"env_prefix": "RADIUS_"}

    server: str = "localhost"
    secret: str = "testing123"
    auth_port: int = 1812
    acct_port: int = 1813
    timeout: int = 10
    retries: int = 3


class SessionGrant(BaseModel):
    """Parsed Access-Accept response with VSA grant attributes."""

    session_timeout: int = 1800
    token_budget: int = 50000
    model_allowed: str = "claude-haiku-4-5"
    allowed_domains: str = "mlssoccer.com"
    browser_enabled: bool = False
    shell_enabled: bool = False
    max_pages: int = 20
    max_llm_calls: int = 100
    output_queue: str = "match_processing"
    monthly_budget: int = 0
    monthly_used: int = 0

    @property
    def budget_remaining(self) -> int:
        return self.token_budget - self.monthly_used


class AccountingUpdate(BaseModel):
    """Token and activity counters sent in accounting packets."""

    tokens_used: int = 0
    pages_visited: int = 0
    llm_calls_made: int = 0
    tool_calls_made: int = 0
    matches_found: int = 0
    session_time: int = 0
