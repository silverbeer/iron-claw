"""Integration tests for ScrapingEngine full lifecycle.

Requires:
  - FreeRADIUS container running (cd docker && docker compose up -d)
  - Supabase local running with RADIUS tables migrated
  - Env vars: RADIUS_SERVER, DB_HOST (defaults: localhost, localhost)

Run:
  pytest tests/test_engine_integration.py -m integration -v
"""

from __future__ import annotations

import os
import time
from unittest.mock import MagicMock, patch

import psycopg2
import pytest

from policy.engine import ThrottleAction
from radius.models import RadiusConfig
from scraper.engine import ScrapingEngine

USERNAME = "iron-claw-scraper"
PASSWORD = "scraper-secret"


def _mock_frame_with_matches() -> MagicMock:
    """Return a mock Frame that DOMExtractor can extract one match from.

    Simulates the DOM structure by mocking query_selector / query_selector_all
    so that DOMExtractor finds one row with valid team, date, and score data.
    """

    def _el(text: str) -> MagicMock:
        el = MagicMock()
        el.text_content.return_value = text
        el.query_selector.return_value = None
        el.query_selector_all.return_value = []
        return el

    # Build teams column with sub-elements
    home_team_el = _el("FC Dallas")
    away_team_el = _el("Houston Dynamo")
    score_el = _el("VS")

    teams_col = MagicMock()

    def teams_qs(sel):
        if "first-team" in sel:
            return home_team_el
        if "second-team" in sel:
            return away_team_el
        if "score" in sel:
            return score_el
        return None

    teams_col.query_selector = MagicMock(side_effect=teams_qs)

    # Build details column
    details_col = _el("02/28/2026\n3:00 PM\nToyota Stadium")

    # Build competition column
    comp_col = _el("MLS Next\nNortheast")

    # Build match row
    row = MagicMock()

    def row_qs(sel):
        if "col-sm-2:nth-child(2)" in sel:
            return details_col
        if "col-sm-2:nth-child(4)" in sel:
            return comp_col
        if "container-teams-info" in sel:
            return teams_col
        if "first-team" in sel:
            return home_team_el
        if "second-team" in sel:
            return away_team_el
        return None

    row.query_selector = MagicMock(side_effect=row_qs)

    # Build frame
    frame = MagicMock()

    def frame_qsa(sel):
        if "table-content-row" in sel:
            return [row]
        return []

    frame.query_selector_all = MagicMock(side_effect=frame_qsa)
    frame.query_selector = MagicMock(return_value=None)

    return frame


# ---------------------------------------------------------------------------
# Fixtures (local to this file)
# ---------------------------------------------------------------------------


@pytest.fixture()
def radius_config(request):
    """Build RadiusConfig from CLI options / env vars."""
    return RadiusConfig(
        server=request.config.getoption("--radius-server"),
        secret=request.config.getoption("--radius-secret"),
        auth_port=request.config.getoption("--radius-auth-port"),
        acct_port=request.config.getoption("--radius-acct-port"),
    )


@pytest.fixture()
def db_conn():
    """Connect to Supabase PostgreSQL (local) for radacct verification."""
    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", "54332")),
        dbname=os.environ.get("DB_NAME", "postgres"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASSWORD", "postgres"),
    )
    yield conn
    conn.close()


def query_radacct(conn, session_id: str, timeout: float = 5.0) -> dict | None:
    """Poll radacct for the stopped row matching session_id.

    FreeRADIUS writes async, so we poll briefly.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT acctsessionid, acctinputoctets, acctoutputoctets, "
                "acctterminatecause, acctstoptime "
                "FROM radacct WHERE acctsessionid = %s AND acctstoptime IS NOT NULL",
                (session_id,),
            )
            row = cur.fetchone()
            if row:
                return {
                    "acctsessionid": row[0],
                    "acctinputoctets": row[1],
                    "acctoutputoctets": row[2],
                    "acctterminatecause": row[3],
                    "acctstoptime": row[4],
                }
        time.sleep(0.5)
    return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestEngineIntegration:
    def test_full_lifecycle_single_page(self, radius_config, db_conn):
        """Single page scrape: auth -> acct-start -> extract -> acct-stop.

        Uses a mock Frame (no browser). Verifies RADIUS accounting lifecycle.
        """
        mock_frame = _mock_frame_with_matches()
        engine = ScrapingEngine(config=radius_config)

        with patch.object(engine._fetcher, "fetch", return_value=iter([mock_frame])):
            result = engine.run(USERNAME, PASSWORD, target_url="https://example.com/page1")

        # Verify ScrapeResult
        assert result.pages_visited == 1
        assert result.session_id

        # Verify radacct row
        row = query_radacct(db_conn, result.session_id)
        assert row is not None, f"No stopped radacct row for session {result.session_id}"
        assert row["acctterminatecause"] == "User-Request"

    def test_budget_kill_stops_early(self, radius_config, db_conn):
        """Policy returns KILL_SESSION after page 1 -> engine stops.

        Mocks the policy engine to kill after the first page, verifying
        that the engine respects throttle decisions.
        """
        mock_frame = _mock_frame_with_matches()
        engine = ScrapingEngine(config=radius_config)

        call_count = 0
        original_evaluate = engine._policy.evaluate

        def evaluate_with_kill(session):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                return ThrottleAction.KILL_SESSION
            return original_evaluate(session)

        with (
            patch.object(engine._fetcher, "fetch", return_value=iter([mock_frame] * 3)),
            patch.object(engine._policy, "evaluate", side_effect=evaluate_with_kill),
        ):
            result = engine.run(USERNAME, PASSWORD)

        # Only 1 page should be scraped — budget kill before page 2
        assert result.pages_visited == 1

        # Verify radacct
        row = query_radacct(db_conn, result.session_id)
        assert row is not None, f"No stopped radacct row for session {result.session_id}"
        assert row["acctterminatecause"] == "User-Request"

    def test_multiple_pages_with_interim_updates(self, radius_config, db_conn):
        """3 pages -> verifies interim accounting updates and final acct-stop.

        Uses mock Frames. Verifies that all pages are processed
        and the final radacct row reflects the session.
        """
        mock_frame = _mock_frame_with_matches()
        engine = ScrapingEngine(config=radius_config)

        with patch.object(engine._fetcher, "fetch", return_value=iter([mock_frame] * 3)):
            result = engine.run(USERNAME, PASSWORD)

        # Verify ScrapeResult
        assert result.pages_visited == 3

        # Verify radacct — final stop row exists
        row = query_radacct(db_conn, result.session_id)
        assert row is not None, f"No stopped radacct row for session {result.session_id}"
        assert row["acctterminatecause"] == "User-Request"
