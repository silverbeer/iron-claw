"""Pagination detection and navigation for MLS Next schedule iframe."""

from __future__ import annotations

import structlog
from playwright.sync_api import Frame

logger = structlog.get_logger()

PAGINATION_SELECTORS = [
    ".pagination",
    "nav[aria-label*='pagination']",
    "[class*='pagination']",
    ".pager",
]


def has_next_page(iframe: Frame) -> bool:
    """Return True if a clickable 'Next' button exists in the iframe."""
    try:
        btn = iframe.get_by_text("Next", exact=True)
        return btn.count() > 0
    except Exception:
        return False


def get_total_pages(iframe: Frame) -> int:
    """Scan pagination controls and return the highest page number found.

    Returns 1 (single page) when no pagination is detected.
    """
    for sel in PAGINATION_SELECTORS:
        try:
            if iframe.query_selector(sel):
                break
        except Exception:
            continue
    else:
        if not has_next_page(iframe):
            logger.info("pagination.single_page")
            return 1

    max_page = 1
    for num in range(2, 21):
        try:
            btn = iframe.get_by_text(str(num), exact=True)
            if btn.count() > 0:
                max_page = num
        except Exception:
            break

    logger.info("pagination.total_pages", pages=max_page)
    return max_page


def navigate_next_page(iframe: Frame) -> bool:
    """Click the 'Next' button and wait for the page transition.

    Returns True on success, False if the button is missing or click fails.
    """
    try:
        btn = iframe.get_by_text("Next", exact=True)
        if btn.count() == 0:
            logger.info("pagination.no_next_button")
            return False
        btn.first.click()
        iframe.page.wait_for_timeout(2000)
        logger.debug("pagination.navigated_next")
        return True
    except Exception:
        logger.exception("pagination.next_error")
        return False
