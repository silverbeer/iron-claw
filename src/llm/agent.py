"""PydanticAI match extraction agent."""

from __future__ import annotations

from pydantic_ai import Agent

from llm.deps import AgentDeps
from llm.result import AgentResult
from llm.tools import schedule_match, score_match

SYSTEM_PROMPT = """\
You are a match data extractor and processor for MLS Next soccer.

Given HTML from a match schedule page, you must:

1. Extract all match information into structured MatchData records.
2. For each match with status 'scheduled', call the schedule_match tool.
3. For each match with status 'final' (has scores), call the score_match tool.

Each match should have: home_team, away_team, home_score (null if not played),
away_score (null if not played), date (ISO 8601), time, venue, competition, status.

Status values: 'scheduled' (upcoming), 'in_progress' (live), 'final' (completed).
"""

match_agent = Agent(
    output_type=AgentResult,
    deps_type=AgentDeps,
    system_prompt=SYSTEM_PROMPT,
    tools=[schedule_match, score_match],
    retries=1,
)
