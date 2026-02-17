"""Apply age-group and division filters via iframe Bootstrap Select dropdowns."""

from __future__ import annotations

import structlog
from playwright.sync_api import Frame

logger = structlog.get_logger()

AGE_GROUP_VALUES: dict[str, str] = {
    "U13": "21",
    "U14": "22",
    "U15": "33",
    "U16": "14",
    "U17": "15",
    "U19": "26",
}

DIVISION_VALUES: dict[str, str] = {
    "Central": "34",
    "Northeast": "41",
    "East": "35",
    "Mid-Atlantic": "68",
    "Florida": "46",
    "Southwest": "36",
    "Southeast": "37",
    "Northwest": "38",
    "Great Lakes": "39",
    "Texas": "40",
    "California": "42",
}


def apply_filters(iframe: Frame, age_group: str, division: str) -> None:
    """Apply age group and division filters inside the iframe.

    Uses direct ``select_option()`` on the hidden ``<select>`` elements
    (Strategy 1 from match-scraper — the most reliable approach).

    Raises ValueError if an unknown age group or division is provided.
    """
    _apply_age_group(iframe, age_group)
    _apply_division(iframe, division)


def _apply_age_group(iframe: Frame, age_group: str) -> None:
    value = AGE_GROUP_VALUES.get(age_group)
    if value is None:
        msg = f"Unknown age group {age_group!r}. Valid: {sorted(AGE_GROUP_VALUES)}"
        raise ValueError(msg)

    for attempt in range(3):
        try:
            sel = iframe.locator("select[js-age]")
            if sel.count() > 0:
                sel.select_option(value=value)
                logger.info("filters.age_group_applied", age_group=age_group, value=value)
                iframe.page.wait_for_timeout(2000)
                return
        except Exception:
            logger.debug("filters.age_group_retry", attempt=attempt + 1)
            iframe.page.wait_for_timeout(3000)

    msg = f"Could not apply age group filter {age_group!r} after 3 attempts"
    raise RuntimeError(msg)


def _apply_division(iframe: Frame, division: str) -> None:
    value = DIVISION_VALUES.get(division)
    if value is None:
        msg = f"Unknown division {division!r}. Valid: {sorted(DIVISION_VALUES)}"
        raise ValueError(msg)

    for attempt in range(3):
        try:
            selects = iframe.locator("select").all()
            if len(selects) >= 4:
                selects[3].select_option(value=value)
                logger.info("filters.division_applied", division=division, value=value)
                iframe.page.wait_for_timeout(2000)
                return
        except Exception:
            logger.debug("filters.division_retry", attempt=attempt + 1)
            iframe.page.wait_for_timeout(3000)

    msg = f"Could not apply division filter {division!r} after 3 attempts"
    raise RuntimeError(msg)
