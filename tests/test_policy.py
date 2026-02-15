"""Unit tests for the throttle policy engine."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from policy.engine import PolicyEngine
from policy.rules import ThrottleAction


def _mock_session(budget_percentage: float):
    """Create a mock session with a given budget percentage."""
    session = MagicMock()
    session.budget_percentage = budget_percentage
    return session


class TestPolicyEngine:
    """Tests for throttle ladder evaluation."""

    def test_normal_under_70_percent(self):
        engine = PolicyEngine()
        assert engine.evaluate(_mock_session(0.0)) == ThrottleAction.NONE
        assert engine.evaluate(_mock_session(50.0)) == ThrottleAction.NONE
        assert engine.evaluate(_mock_session(69.9)) == ThrottleAction.NONE

    def test_downgrade_at_70_percent(self):
        engine = PolicyEngine()
        assert engine.evaluate(_mock_session(70.0)) == ThrottleAction.DOWNGRADE_MODEL
        assert engine.evaluate(_mock_session(80.0)) == ThrottleAction.DOWNGRADE_MODEL
        assert engine.evaluate(_mock_session(89.9)) == ThrottleAction.DOWNGRADE_MODEL

    def test_reduce_pages_at_90_percent(self):
        engine = PolicyEngine()
        assert engine.evaluate(_mock_session(90.0)) == ThrottleAction.REDUCE_PAGES
        assert engine.evaluate(_mock_session(95.0)) == ThrottleAction.REDUCE_PAGES
        assert engine.evaluate(_mock_session(99.9)) == ThrottleAction.REDUCE_PAGES

    def test_kill_at_100_percent(self):
        engine = PolicyEngine()
        assert engine.evaluate(_mock_session(100.0)) == ThrottleAction.KILL_SESSION
        assert engine.evaluate(_mock_session(150.0)) == ThrottleAction.KILL_SESSION

    def test_exact_boundaries(self):
        """Verify boundary values fall into correct buckets."""
        engine = PolicyEngine()
        assert engine.evaluate(_mock_session(70.0)) == ThrottleAction.DOWNGRADE_MODEL
        assert engine.evaluate(_mock_session(90.0)) == ThrottleAction.REDUCE_PAGES
        assert engine.evaluate(_mock_session(100.0)) == ThrottleAction.KILL_SESSION
