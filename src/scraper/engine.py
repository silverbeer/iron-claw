"""Scraping engine — orchestrates the RADIUS-controlled LLM scraping session."""

from __future__ import annotations

import structlog

from llm.anthropic_provider import AnthropicProvider
from llm.mock_provider import MockProvider
from llm.protocol import LLMProvider
from models.match_data import MatchData
from models.session import ScrapingSession
from policy.engine import PolicyEngine, ThrottleAction
from radius.client import RadiusSessionClient
from radius.models import RadiusConfig
from scraper.page_fetcher import PageFetcher

logger = structlog.get_logger()

DEFAULT_TARGET_URL = "https://www.mlssoccer.com/mlsnext/schedule"


class ScrapeResult:
    """Result of a scraping session."""

    def __init__(self, session: ScrapingSession) -> None:
        self.matches_found = session.matches_found
        self.tokens_used = session.tokens_used
        self.pages_visited = session.pages_visited
        self.llm_calls_made = session.llm_calls_made
        self.matches = list(session.matches)


class ScrapingEngine:
    """Orchestrates the full RADIUS-controlled scraping lifecycle.

    1. Authenticate with RADIUS -> get session grant
    2. Enforce grant constraints (model, pages, domains)
    3. Send Acct-Start
    4. For each page: fetch HTML, extract matches via LLM, track tokens
    5. After each page: evaluate throttle policy
    6. Send Acct-Stop (always, even on error)
    """

    def __init__(
        self,
        config: RadiusConfig | None = None,
        dry_run: bool = False,
        llm_provider: LLMProvider | None = None,
    ) -> None:
        self._config = config or RadiusConfig()
        self._radius = RadiusSessionClient(self._config)
        self._fetcher = PageFetcher()
        self._policy = PolicyEngine()
        self._dry_run = dry_run
        self._llm_provider = llm_provider

    def run(
        self,
        username: str,
        password: str,
        target_url: str | None = None,
    ) -> ScrapeResult:
        """Execute the full scraping session."""
        # 1. Authenticate
        grant = self._radius.authenticate(username, password)

        # 2. Choose LLM provider
        provider: LLMProvider
        if self._llm_provider:
            provider = self._llm_provider
        elif self._dry_run:
            provider = MockProvider(model=grant.model_allowed)
        else:
            provider = AnthropicProvider(model=grant.model_allowed)

        # 3. Create session
        session_id = self._radius.generate_session_id()
        session = ScrapingSession(
            session_id=session_id,
            username=username,
            grant=grant,
        )

        # 4. Acct-Start
        self._radius.acct_start(session_id, username)
        terminate_cause = "User-Request"

        try:
            # 5. Scrape pages
            url = target_url or DEFAULT_TARGET_URL
            self._scrape_pages(session, provider, [url])
        except Exception:
            terminate_cause = "NAS-Error"
            logger.exception("scraper.error", session_id=session_id)
        finally:
            # 6. Acct-Stop (always)
            self._radius.acct_stop(
                session_id,
                username,
                session.to_accounting_update(),
                terminate_cause,
            )

        return ScrapeResult(session)

    def _scrape_pages(
        self,
        session: ScrapingSession,
        provider: LLMProvider,
        urls: list[str],
    ) -> None:
        """Scrape a list of URLs with throttle policy enforcement."""
        for url in urls:
            if session.pages_remaining <= 0:
                logger.info("scraper.max_pages_reached", session_id=session.session_id)
                break

            if session.llm_calls_remaining <= 0:
                logger.info("scraper.max_llm_calls_reached", session_id=session.session_id)
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

            # Fetch page
            try:
                html = self._fetcher.fetch(url)
            except Exception:
                logger.exception("scraper.fetch_error", url=url)
                continue

            session.add_page()

            # Extract matches via LLM
            try:
                raw_matches, usage = provider.extract_matches(html)
            except Exception:
                logger.exception("scraper.llm_error", url=url)
                continue

            session.add_llm_call()
            session.add_tokens(usage.total_tokens)

            # Parse and store matches
            for raw in raw_matches:
                try:
                    match = MatchData.model_validate(raw)
                    session.add_match(match)
                except Exception:
                    logger.warning("scraper.match_parse_error", raw=raw)

            # Send interim accounting update
            self._radius.acct_interim(
                session.session_id,
                session.username,
                session.to_accounting_update(),
            )

            logger.info(
                "scraper.page_complete",
                url=url,
                matches=len(raw_matches),
                tokens_total=session.tokens_used,
                budget_pct=f"{session.budget_percentage:.1f}%",
            )
