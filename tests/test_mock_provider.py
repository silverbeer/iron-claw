"""Unit tests for the PydanticAI match agent with TestModel."""

from __future__ import annotations

from pydantic_ai.models.test import TestModel

from llm.agent import match_agent
from llm.deps import AgentDeps
from llm.result import AgentResult
from models.session import ScrapingSession
from mq.client import MatchQueueClient
from radius.models import SessionGrant


def _make_deps() -> AgentDeps:
    """Create AgentDeps with a disconnected queue client."""
    grant = SessionGrant()
    session = ScrapingSession(session_id="test-001", username="test", grant=grant)
    queue = MatchQueueClient()
    return AgentDeps(queue_client=queue, session=session, grant=grant)


class TestMatchAgent:
    def test_returns_agent_result(self):
        result = match_agent.run_sync(
            "<html>test</html>",
            deps=_make_deps(),
            model=TestModel(call_tools=[]),
        )
        assert isinstance(result.output, AgentResult)
        assert isinstance(result.output.matches, list)

    def test_reports_usage(self):
        result = match_agent.run_sync(
            "<html>test</html>",
            deps=_make_deps(),
            model=TestModel(call_tools=[]),
        )
        usage = result.usage()
        assert usage.requests >= 1

    def test_actions_default_empty(self):
        result = match_agent.run_sync(
            "<html>test</html>",
            deps=_make_deps(),
            model=TestModel(call_tools=[]),
        )
        assert isinstance(result.output.actions, list)
