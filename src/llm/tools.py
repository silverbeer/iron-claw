"""PydanticAI tool functions for the match extraction agent."""

from __future__ import annotations

import structlog
from pydantic_ai import RunContext

from llm.deps import AgentDeps
from models.match_data import MatchData

logger = structlog.get_logger()


def schedule_match(ctx: RunContext[AgentDeps], match: MatchData) -> str:
    """Publish a scheduled match to the processing queue.

    Use this when you find a match with status 'scheduled' that should be
    tracked. This publishes the match to RabbitMQ for downstream processing.

    Args:
        match: The match data to schedule.
    """
    ctx.deps.queue_client.submit([match])
    logger.info("tool.schedule_match", home=match.home_team, away=match.away_team, date=match.date)
    return f"Scheduled: {match.home_team} vs {match.away_team} on {match.date}"


def score_match(
    ctx: RunContext[AgentDeps],
    home_team: str,
    away_team: str,
    date: str,
    home_score: int,
    away_score: int,
) -> str:
    """Record or update the final score for a match.

    Use this when you find a match with status 'final' that has scores.
    Creates the match record and publishes to the queue.

    Args:
        home_team: Home team name.
        away_team: Away team name.
        date: Match date (ISO 8601).
        home_score: Home team final score.
        away_score: Away team final score.
    """
    match = MatchData(
        home_team=home_team,
        away_team=away_team,
        date=date,
        home_score=home_score,
        away_score=away_score,
        status="final",
    )
    ctx.deps.queue_client.submit([match])
    logger.info(
        "tool.score_match",
        home=home_team,
        away=away_team,
        score=f"{home_score}-{away_score}",
        date=date,
    )
    return f"Scored: {home_team} {home_score}-{away_score} {away_team} on {date}"
