"""Match data model — contract for match records submitted to missing-table."""

from __future__ import annotations

from pydantic import BaseModel


class MatchData(BaseModel):
    """A single match record extracted by the LLM scraper."""

    home_team: str
    away_team: str
    home_score: int | None = None
    away_score: int | None = None
    date: str
    time: str | None = None
    venue: str | None = None
    competition: str = "MLS Next"
    status: str = "scheduled"
