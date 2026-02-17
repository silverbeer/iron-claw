"""Scraping engine — orchestrates the RADIUS-controlled scraping session.

Uses deterministic DOM extraction (CSS selectors) instead of LLM-based
extraction.  The PydanticAI agent layer (src/llm/) is kept for future
agentic features but is not called during normal match extraction.
"""

from __future__ import annotations

import structlog

from models.match_data import MatchData
from models.session import ScrapingSession
from mq.client import MatchQueueClient, QueueConfig
from policy.engine import PolicyEngine, ThrottleAction
from radius.client import RadiusSessionClient
from radius.models import RadiusConfig
from scraper.dom_extractor import DOMExtractor
from scraper.playwright_fetcher import PlaywrightFetcher, ScrapeConfig

logger = structlog.get_logger()

DEFAULT_TARGET_URL = "https://www.mlssoccer.com/mlsnext/schedule"


class ScrapeResult:
    """Result of a scraping session."""

    def __init__(self, session: ScrapingSession) -> None:
        self.session_id = session.session_id
        self.matches_found = session.matches_found
        self.tokens_used = session.tokens_used
        self.pages_visited = session.pages_visited
        self.matches = list(session.matches)
        self.queued: list[MatchData] = []


class ScrapingEngine:
    """Orchestrates the full RADIUS-controlled scraping lifecycle.

    1. Authenticate with RADIUS -> get session grant
    2. Enforce grant constraints (pages, domains)
    3. Send Acct-Start
    4. For each page: extract matches via DOMExtractor, route to queue
    5. After each page: evaluate throttle policy
    6. Send Acct-Stop (always, even on error)
    """

    def __init__(
        self,
        config: RadiusConfig | None = None,
        dry_run: bool = False,
        scrape_config: ScrapeConfig | None = None,
        queue_config: QueueConfig | None = None,
        _test_model: object | None = None,
    ) -> None:
        self._config = config or RadiusConfig()
        self._radius = RadiusSessionClient(self._config)
        self._fetcher = PlaywrightFetcher(scrape_config)
        self._policy = PolicyEngine()
        self._dry_run = dry_run
        self._queue = MatchQueueClient(queue_config)
        self._extractor = DOMExtractor()
        # _test_model kept for integration test compatibility (unused by extractor)
        self._test_model = _test_model

    def run(
        self,
        username: str,
        password: str,
        target_url: str | None = None,
    ) -> ScrapeResult:
        """Execute the full scraping session."""
        # 1. Authenticate
        grant = self._radius.authenticate(username, password)

        # 2. Create session
        session_id = self._radius.generate_session_id()
        session = ScrapingSession(
            session_id=session_id,
            username=username,
            grant=grant,
        )

        # 3. Acct-Start
        self._radius.acct_start(session_id, username)
        terminate_cause = "User-Request"
        result = ScrapeResult(session)

        try:
            # 4. Scrape pages (fetcher handles pagination internally)
            url = target_url or DEFAULT_TARGET_URL
            self._scrape_pages(session, url, result)
        except Exception:
            terminate_cause = "NAS-Error"
            logger.exception("scraper.error", session_id=session_id)
        finally:
            # 5. Acct-Stop (always)
            self._radius.acct_stop(
                session_id,
                username,
                session.to_accounting_update(),
                terminate_cause,
            )

        # Refresh result counts from final session state
        result.matches_found = session.matches_found
        result.pages_visited = session.pages_visited
        result.matches = list(session.matches)
        return result

    def _scrape_pages(
        self,
        session: ScrapingSession,
        url: str,
        result: ScrapeResult,
    ) -> None:
        """Consume pages from the fetcher generator with throttle enforcement."""
        for iframe in self._fetcher.fetch(url):
            if session.pages_remaining <= 0:
                logger.info("scraper.max_pages_reached", session_id=session.session_id)
                break

            # Check throttle policy before each page
            action = self._policy.evaluate(session)
            if action == ThrottleAction.KILL_SESSION:
                logger.warning("scraper.budget_exceeded", session_id=session.session_id)
                break
            if action == ThrottleAction.REDUCE_PAGES:
                session.grant.max_pages = min(session.grant.max_pages, session.pages_visited + 5)
                logger.info(
                    "scraper.pages_reduced",
                    new_max=session.grant.max_pages,
                )

            session.add_page()

            # Deterministic extraction — zero LLM tokens
            try:
                matches = self._extractor.extract(iframe)
            except Exception:
                logger.exception("scraper.extraction_error")
                continue

            # Record matches and route to queue
            for match in matches:
                session.add_match(match)
                if match.status in ("scheduled", "final"):
                    try:
                        self._queue.submit([match])
                        result.queued.append(match)
                    except Exception:
                        summary = f"{match.home_team} vs {match.away_team}"
                        logger.exception("scraper.queue_error", match=summary)

            # Send interim accounting update
            self._radius.acct_interim(
                session.session_id,
                session.username,
                session.to_accounting_update(),
            )

            logger.info(
                "scraper.page_complete",
                page=session.pages_visited,
                matches=len(matches),
            )
