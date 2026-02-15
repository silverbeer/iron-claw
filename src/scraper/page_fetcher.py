"""Page fetcher — retrieves HTML from URLs using httpx."""

from __future__ import annotations

import httpx
import structlog

logger = structlog.get_logger()


class PageFetcher:
    """Fetches HTML content from URLs."""

    def __init__(self, timeout: int = 30) -> None:
        self._timeout = timeout

    def fetch(self, url: str) -> str:
        """Fetch a URL and return the HTML body.

        Raises:
            httpx.HTTPStatusError: On non-2xx responses.
        """
        logger.info("page_fetcher.fetch", url=url)
        response = httpx.get(url, timeout=self._timeout, follow_redirects=True)
        response.raise_for_status()
        length = len(response.text)
        logger.info("page_fetcher.fetched", url=url, status=response.status_code, length=length)
        return response.text
