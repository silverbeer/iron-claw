"""Structured output models for the PydanticAI match agent."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from models.match_data import MatchData


class AgentAction(BaseModel):
    """A tool action taken by the agent during a run."""

    action: Literal["scheduled", "scored"]
    match_summary: str
    published_to_queue: bool


class AgentResult(BaseModel):
    """Structured result returned by the match extraction agent."""

    matches: list[MatchData]
    actions: list[AgentAction] = []
