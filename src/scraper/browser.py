"""Sync Playwright browser session context manager for MLS Next scraping."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

import structlog
from playwright.sync_api import Frame, Page, sync_playwright

from scraper.consent import dismiss_consent

if TYPE_CHECKING:
    from scraper.playwright_fetcher import ScrapeConfig

logger = structlog.get_logger()

MLS_NEXT_URL = "https://www.mlssoccer.com/mlsnext/schedule/all/"

IFRAME_SELECTOR = 'main[role="main"] iframe'


@contextmanager
def browser_session(config: ScrapeConfig) -> Iterator[tuple[Page, Frame]]:
    """Launch headless Chromium, navigate to MLS Next, and yield (page, iframe).

    On exit the browser context and browser are closed unconditionally.
    """
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=config.headless,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-first-run",
                "--no-zygote",
                "--single-process",
            ],
        )
        context = browser.new_context(viewport={"width": 1280, "height": 720})
        context.set_default_timeout(config.timeout)
        page = context.new_page()

        logger.info("browser.navigating", url=MLS_NEXT_URL)
        page.goto(MLS_NEXT_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)  # let async scripts (consent banner) load
        dismiss_consent(page)

        iframe_el = page.wait_for_selector(IFRAME_SELECTOR)
        if iframe_el is None:
            msg = f"Iframe not found: {IFRAME_SELECTOR}"
            raise RuntimeError(msg)
        iframe = iframe_el.content_frame()
        if iframe is None:
            msg = "content_frame() returned None"
            raise RuntimeError(msg)

        page.wait_for_timeout(5000)  # let iframe fully load
        logger.info("browser.ready")

        try:
            yield page, iframe
        finally:
            context.close()
            browser.close()
            logger.info("browser.closed")
