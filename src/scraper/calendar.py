"""Daterangepicker calendar navigation for MLS Next schedule iframe.

Ported from match-scraper calendar_interaction.py (sync Playwright).
Handles same-month, adjacent-month, and multi-month date ranges.
"""

from __future__ import annotations

import re
from datetime import date

import structlog
from playwright.sync_api import Frame

logger = structlog.get_logger()

DATE_FIELD_SELECTOR = 'input[name="datefilter"]'
CALENDAR_SELECTOR = ".daterangepicker"

MONTH_NAMES: dict[str, int] = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}


def set_date_range(iframe: Frame, start: date, end: date) -> None:
    """Open the daterangepicker, select *start* .. *end*, and click Apply.

    Three strategies depending on how far apart the months are:

    * **same month (diff=0)**: both dates on the left calendar panel.
    * **adjacent months (diff=1)**: start on left panel, end on right panel.
    * **wide range (diff>=2)**: navigate to start month, click start; navigate
      to end month, click end.

    Raises RuntimeError on failure.
    """
    # Open the calendar picker
    date_field = iframe.locator(DATE_FIELD_SELECTOR)
    if date_field.count() == 0:
        msg = f"Date field not found: {DATE_FIELD_SELECTOR}"
        raise RuntimeError(msg)

    date_field.click()
    iframe.page.wait_for_timeout(2000)

    if iframe.locator(CALENDAR_SELECTOR).count() == 0:
        msg = "Daterangepicker did not open"
        raise RuntimeError(msg)

    logger.info("calendar.opened")

    month_diff = (end.year - start.year) * 12 + (end.month - start.month)

    if month_diff == 0:
        _select_same_month(iframe, start, end)
    elif month_diff == 1:
        _select_adjacent_months(iframe, start, end)
    else:
        _select_wide_range(iframe, start, end)

    _click_apply(iframe)
    iframe.page.wait_for_timeout(3000)
    logger.info("calendar.date_range_set", start=str(start), end=str(end))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _select_same_month(iframe: Frame, start: date, end: date) -> None:
    """Both dates are in the same month — navigate left panel there, click both."""
    _navigate_to_month(iframe, start.month, start.year)
    iframe.page.wait_for_timeout(1500)
    _click_day(iframe, "left", start.day)
    _click_day(iframe, "left", end.day)


def _select_adjacent_months(iframe: Frame, start: date, end: date) -> None:
    """Start month on left panel, next month on right panel (diff=1).

    Navigate so the left calendar shows the start month; the right calendar
    will automatically show the next month.
    """
    _navigate_to_month(iframe, start.month, start.year)
    iframe.page.wait_for_timeout(1500)
    _click_day(iframe, "left", start.day)
    _click_day(iframe, "right", end.day)


def _select_wide_range(iframe: Frame, start: date, end: date) -> None:
    """Months are >=2 apart.  Navigate to start, click; navigate to end, click."""
    _navigate_to_month(iframe, start.month, start.year)
    iframe.page.wait_for_timeout(1500)
    _click_day(iframe, "left", start.day)

    _navigate_to_month(iframe, end.month, end.year)
    iframe.page.wait_for_timeout(1500)
    _click_day(iframe, "left", end.day)


def _click_day(iframe: Frame, side: str, day: int) -> None:
    """Click a day number on the left or right calendar panel."""
    selectors = [
        f'.daterangepicker .drp-calendar.{side} td:has-text("{day}"):not(.off)',
        f'.drp-calendar.{side} .calendar-table td:has-text("{day}"):not(.off)',
    ]
    for sel in selectors:
        loc = iframe.locator(sel)
        if loc.count() > 0:
            loc.first.click()
            logger.debug("calendar.day_clicked", side=side, day=day)
            iframe.page.wait_for_timeout(1000)
            return

    msg = f"Could not click day {day} on {side} calendar"
    raise RuntimeError(msg)


def _click_apply(iframe: Frame) -> None:
    """Click the daterangepicker Apply button."""
    for sel in [
        ".daterangepicker .applyBtn",
        ".daterangepicker button.applyBtn",
        ".applyBtn",
    ]:
        try:
            btn = iframe.locator(sel)
            if btn.count() > 0:
                btn.first.click()
                logger.info("calendar.apply_clicked")
                return
        except Exception:
            continue

    msg = "Could not click Apply button"
    raise RuntimeError(msg)


# ---------------------------------------------------------------------------
# Month navigation
# ---------------------------------------------------------------------------


def _navigate_to_month(iframe: Frame, target_month: int, target_year: int) -> None:
    """Click prev/next arrows until the LEFT calendar shows *target_month/target_year*."""
    cur_month, cur_year = _get_left_month_year(iframe)
    if cur_month is None or cur_year is None:
        msg = "Cannot read current month/year from daterangepicker"
        raise RuntimeError(msg)

    if cur_month == target_month and cur_year == target_year:
        return

    current_total = cur_year * 12 + cur_month
    target_total = target_year * 12 + target_month
    diff = target_total - current_total
    forward = diff > 0
    iterations = min(abs(diff), 24)

    arrow_sel = ".next > span" if forward else ".prev > span"

    for i in range(iterations):
        arrow = iframe.locator(arrow_sel)
        if arrow.count() == 0:
            msg = f"Navigation arrow not found: {arrow_sel}"
            raise RuntimeError(msg)
        arrow.first.click()
        iframe.page.wait_for_timeout(500)

        m, y = _get_left_month_year(iframe)
        if m == target_month and y == target_year:
            logger.debug("calendar.navigated", month=target_month, year=target_year, clicks=i + 1)
            return

    msg = f"Could not navigate to {target_month}/{target_year} within {iterations} clicks"
    raise RuntimeError(msg)


def _get_left_month_year(iframe: Frame) -> tuple[int | None, int | None]:
    """Read the month/year header from the left calendar panel."""
    for sel in [
        ".daterangepicker .drp-calendar.left .month",
        ".daterangepicker .drp-calendar.left th.month",
        ".drp-calendar.left .calendar-table th.month",
    ]:
        loc = iframe.locator(sel)
        if loc.count() > 0:
            text = loc.first.text_content()
            if text:
                return _parse_month_year(text.strip())
    return None, None


def _parse_month_year(text: str) -> tuple[int | None, int | None]:
    """Parse ``'Feb 2026'`` or ``'February 2026'`` into (month, year)."""
    match = re.search(r"(\w+)\s*,?\s*(\d{4})", text)
    if not match:
        return None, None
    month_str, year_str = match.groups()
    month = MONTH_NAMES.get(month_str.lower())
    if month is None:
        return None, None
    return month, int(year_str)
