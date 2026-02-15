"""Policy engine — evaluates throttle ladder against session state."""

from __future__ import annotations

import structlog

from policy.rules import DEFAULT_THROTTLE_LADDER, ThrottleAction, ThrottleRule

logger = structlog.get_logger()


class PolicyEngine:
    """Evaluates session budget usage against the throttle ladder."""

    def __init__(self, ladder: list[ThrottleRule] | None = None) -> None:
        self._ladder = ladder or DEFAULT_THROTTLE_LADDER

    def evaluate(self, session) -> ThrottleAction:
        """Evaluate the current session state and return the appropriate action.

        Args:
            session: A ScrapingSession with budget_percentage property.

        Returns:
            The throttle action to take based on budget consumption.
        """
        pct = session.budget_percentage

        for rule in self._ladder:
            if rule.min_pct <= pct < rule.max_pct:
                if rule.action != ThrottleAction.NONE:
                    logger.info(
                        "policy.throttle",
                        action=rule.action.value,
                        budget_pct=f"{pct:.1f}%",
                        detail=rule.detail,
                    )
                return rule.action

        # If nothing matched (shouldn't happen with inf), kill
        logger.warning("policy.no_rule_matched", budget_pct=f"{pct:.1f}%")
        return ThrottleAction.KILL_SESSION
