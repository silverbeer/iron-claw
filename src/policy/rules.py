"""Throttle rules and ladder for budget enforcement."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class ThrottleAction(Enum):
    """Actions the policy engine can take."""

    NONE = "none"
    DOWNGRADE_MODEL = "downgrade_model"
    REDUCE_PAGES = "reduce_pages"
    KILL_SESSION = "kill_session"


class ThrottleRule(BaseModel):
    """A single rule in the throttle ladder."""

    min_pct: float
    max_pct: float
    action: ThrottleAction
    detail: str


DEFAULT_THROTTLE_LADDER: list[ThrottleRule] = [
    ThrottleRule(
        min_pct=0,
        max_pct=70,
        action=ThrottleAction.NONE,
        detail="Normal operation, full speed",
    ),
    ThrottleRule(
        min_pct=70,
        max_pct=90,
        action=ThrottleAction.DOWNGRADE_MODEL,
        detail="Switch to cheaper model",
    ),
    ThrottleRule(
        min_pct=90,
        max_pct=100,
        action=ThrottleAction.REDUCE_PAGES,
        detail="Cap remaining pages to 5",
    ),
    ThrottleRule(
        min_pct=100,
        max_pct=float("inf"),
        action=ThrottleAction.KILL_SESSION,
        detail="Budget exceeded, stop immediately",
    ),
]
