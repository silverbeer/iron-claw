"""PlaywrightFetcher — browser-driven page fetcher that yields Playwright Frames.

Replaces PageFetcher (httpx.get) with headless Chromium navigation through the
MLS Next schedule: consent → iframe → filters → calendar → paginated results.

Yields live Frame objects so the engine can run CSS selectors directly via
DOMExtractor, rather than serialising HTML and re-parsing it.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import TYPE_CHECKING, ClassVar

import structlog
from pydantic import BaseModel, Field

from scraper.browser import browser_session
from scraper.calendar import set_date_range
from scraper.filters import apply_filters
from scraper.pagination import has_next_page, navigate_next_page

if TYPE_CHECKING:
    from playwright.sync_api import Frame

logger = structlog.get_logger()


class ScrapeConfig(BaseModel):
    """Configuration for a single scrape run."""

    age_group: str = "U14"
    division: str = "Northeast"
    start_date: date = Field(default_factory=date.today)
    end_date: date = Field(default_factory=date.today)
    headless: bool = True
    timeout: int = 30_000

    AGE_GROUP_VALUES: ClassVar[dict[str, str]] = {
        "U13": "21", "U14": "22", "U15": "33",
        "U16": "14", "U17": "15", "U19": "26",
    }
    DIVISION_VALUES: ClassVar[dict[str, str]] = {
        "Central": "34", "Northeast": "41", "East": "35",
        "Mid-Atlantic": "68", "Florida": "46", "Southwest": "36",
        "Southeast": "37", "Northwest": "38", "Great Lakes": "39",
        "Texas": "40", "California": "42",
    }


class PlaywrightFetcher:
    """Navigate MLS Next with Playwright and yield a live Frame per page.

    Usage::

        fetcher = PlaywrightFetcher(config)
        for iframe in fetcher.fetch(url):
            matches = DOMExtractor().extract(iframe)
    """

    def __init__(self, config: ScrapeConfig | None = None) -> None:
        self._config = config or ScrapeConfig()

    def fetch(self, url: str) -> Iterator[Frame]:
        """Open the browser, apply filters + date range, and yield the iframe per page.

        *url* is accepted for interface compatibility but ignored — the fetcher
        always navigates to the MLS Next schedule URL configured in browser.py.

        Yields the **live Playwright Frame** so callers can run CSS selectors
        directly against the DOM.
        """
        cfg = self._config

        with browser_session(cfg) as (_page, iframe):
            # Apply age group + division filters
            apply_filters(iframe, cfg.age_group, cfg.division)
            logger.info("fetcher.filters_applied")

            # Set the date range
            set_date_range(iframe, cfg.start_date, cfg.end_date)
            logger.info("fetcher.date_range_set")

            # Yield first page
            page_num = 1
            logger.info("fetcher.page_yielded", page=page_num)
            yield iframe

            # Paginate through remaining pages
            while has_next_page(iframe):
                if not navigate_next_page(iframe):
                    break
                page_num += 1
                logger.info("fetcher.page_yielded", page=page_num)
                yield iframe

        logger.info("fetcher.done", total_pages=page_num)
