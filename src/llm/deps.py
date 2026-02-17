"""Agent dependencies — injected into PydanticAI tool functions via RunContext."""

from __future__ import annotations

from dataclasses import dataclass

from models.session import ScrapingSession
from mq.client import MatchQueueClient
from radius.models import SessionGrant


@dataclass
class AgentDeps:
    """Carries session context into agent tool calls."""

    queue_client: MatchQueueClient
    session: ScrapingSession
    grant: SessionGrant
