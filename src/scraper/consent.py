"""Dismiss cookie consent banner on MLS Next site."""

from __future__ import annotations

import contextlib

import structlog
from playwright.sync_api import Page

logger = structlog.get_logger()

# Banner container selectors (try in order)
BANNER_SELECTORS = [
    "#onetrust-consent-sdk",
    "[id*='onetrust']",
    "[class*='onetrust']",
    "[id*='consent']",
    "[class*='consent']",
    "[class*='cookie-banner']",
    "[class*='privacy-banner']",
]

# Accept button selectors (try in order)
ACCEPT_BUTTON_SELECTORS = [
    "#onetrust-accept-btn-handler",
    "button:has-text('Accept & Continue')",
    "button:has-text('Accept All')",
    "button:has-text('Accept')",
    "#ot-sdk-btn",
    "button[id*='accept']",
]


def dismiss_consent(page: Page, timeout: int = 10_000) -> bool:
    """Click the consent accept button if a banner is present.

    Two strategies:
    1. Look for a known banner container, then click accept inside it.
    2. Fall back to clicking any visible accept button on the page.

    Returns True if dismissed (or no banner found). False on failure.
    """
    try:
        # Strategy 1: Find banner container first
        for selector in BANNER_SELECTORS:
            try:
                page.wait_for_selector(selector, timeout=timeout // len(BANNER_SELECTORS))
                logger.info("consent.banner_detected", selector=selector)
                if _click_accept(page):
                    return True
                break
            except Exception:
                continue

        # Strategy 2: Skip container detection — just try clicking accept buttons directly
        # The banner may use non-standard containers
        logger.debug("consent.trying_direct_button_click")
        if _click_accept(page):
            return True

        logger.info("consent.no_banner")
        return True

    except Exception:
        logger.exception("consent.error")
        return False


def _click_accept(page: Page) -> bool:
    """Try each accept button selector until one works."""
    for selector in ACCEPT_BUTTON_SELECTORS:
        try:
            btn = page.query_selector(selector)
            if btn and btn.is_visible():
                btn.click()
                logger.info("consent.accepted", selector=selector)
                # Wait for banner to disappear
                with contextlib.suppress(Exception):
                    page.wait_for_timeout(2000)
                return True
        except Exception:
            continue
    return False
