"""Deterministic match extraction from MLS Next schedule page.

Ports proven CSS selectors from match-scraper's MLSMatchExtractor to extract
MatchData from a Playwright Frame using the Bootstrap grid layout — zero LLM
tokens, instant, deterministic.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import structlog

from models.match_data import MatchData

if TYPE_CHECKING:
    from playwright.sync_api import ElementHandle, Frame

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# CSS selectors — ported from match-scraper/src/scraper/match_extraction.py
# ---------------------------------------------------------------------------

# Match rows within the Bootstrap grid table
_ROW_SELECTORS = [
    ".container-row .row.table-content-row.hidden-xs",
    ".row.table-content-row.hidden-xs",
    ".table-content-row.hidden-xs",
    ".table-content-row",
]

# Bootstrap grid column selectors for each data field
_COL_DETAILS = ".col-sm-2:nth-child(2)"  # date / time / venue
_COL_COMPETITION = ".col-sm-2:nth-child(4)"  # competition + division
_COL_TEAMS = ".col-sm-6.pad-0 .container-teams-info"

# Team / score selectors within the teams column
_HOME_TEAM = ".container-first-team p"
_AWAY_TEAM = ".container-second-team p"
_SCORE = ".container-score .score-match-table"

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_SCORE_RE = re.compile(r"(\d+)\s*[-\u2013\u2014:]\s*(\d+)")
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*(AM|PM)", re.IGNORECASE)
_DATE_PATTERNS = [
    re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})"),  # MM/DD/YYYY
    re.compile(r"(\d{1,2})/(\d{1,2})/(\d{2})$"),  # MM/DD/YY
    re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})"),  # YYYY-MM-DD
]

_TBD_VALUES = frozenset({"TBD", "VS", "V", "@", "NOT STARTED", "PENDING"})


class DOMExtractor:
    """Deterministic match extraction from MLS Next schedule page."""

    def extract(self, iframe: Frame) -> list[MatchData]:
        """Extract all matches from the current page of the iframe."""
        rows = self._find_match_rows(iframe)
        if not rows:
            logger.info("dom_extractor.no_rows")
            return []

        matches: list[MatchData] = []
        for i, row in enumerate(rows):
            match = self._parse_row(row, i)
            if match:
                matches.append(match)

        logger.info("dom_extractor.extracted", count=len(matches), rows=len(rows))
        return matches

    # ------------------------------------------------------------------
    # Row discovery
    # ------------------------------------------------------------------

    def _find_match_rows(self, iframe: Frame) -> list[ElementHandle]:
        """Try each row selector until we find match rows."""
        for selector in _ROW_SELECTORS:
            rows = iframe.query_selector_all(selector)
            if rows:
                logger.debug("dom_extractor.rows_found", selector=selector, count=len(rows))
                return rows
        return []

    # ------------------------------------------------------------------
    # Per-row parsing
    # ------------------------------------------------------------------

    def _parse_row(self, row: ElementHandle, index: int) -> MatchData | None:
        """Parse a single Bootstrap grid row into MatchData."""
        home_team = self._text(row, _HOME_TEAM)
        away_team = self._text(row, _AWAY_TEAM)

        if not home_team or not away_team:
            logger.debug("dom_extractor.skip_row", index=index, reason="missing_teams")
            return None

        # Details column — date / time / venue
        date_str, time_str, venue = self._parse_details(row)
        if not date_str:
            logger.debug("dom_extractor.skip_row", index=index, reason="no_date")
            return None

        # Convert date to ISO 8601 (YYYY-MM-DD)
        iso_date = self._to_iso_date(date_str)
        if not iso_date:
            logger.debug("dom_extractor.skip_row", index=index, reason="bad_date", raw=date_str)
            return None

        # Score
        home_score, away_score, status = self._parse_score(row)

        # Competition
        competition = self._parse_competition(row)

        return MatchData(
            home_team=home_team,
            away_team=away_team,
            home_score=home_score,
            away_score=away_score,
            date=iso_date,
            time=time_str,
            venue=venue,
            competition=competition,
            status=status,
        )

    # ------------------------------------------------------------------
    # Detail column parsing
    # ------------------------------------------------------------------

    def _parse_details(self, row: ElementHandle) -> tuple[str | None, str | None, str | None]:
        """Extract date, time, venue from the details column.

        Returns (date_str, time_str, venue) — any may be None.
        """
        col = row.query_selector(_COL_DETAILS)
        if not col:
            return None, None, None

        text = col.text_content()
        if not text:
            return None, None, None

        parts = [p.strip() for p in text.strip().split("\n") if p.strip()]

        date_str: str | None = None
        time_str: str | None = None
        venue: str | None = None

        for part in parts:
            # Check for date
            if date_str is None and self._looks_like_date(part):
                date_str = part
                continue

            # Check for time (may be on same line as date or separate)
            if time_str is None and _TIME_RE.search(part):
                time_str = part
                continue

            # Everything else with enough length is likely the venue
            if venue is None and len(part) > 3:
                venue = part

        return date_str, time_str, venue

    # ------------------------------------------------------------------
    # Score parsing
    # ------------------------------------------------------------------

    def _parse_score(self, row: ElementHandle) -> tuple[int | None, int | None, str]:
        """Parse score element and return (home_score, away_score, status)."""
        teams_col = row.query_selector(_COL_TEAMS)
        if not teams_col:
            return None, None, "scheduled"

        score_el = teams_col.query_selector(_SCORE)
        if not score_el:
            return None, None, "scheduled"

        text = (score_el.text_content() or "").replace("\xa0", " ").strip()
        if not text:
            return None, None, "scheduled"

        if text.upper() in _TBD_VALUES:
            return None, None, "scheduled"

        m = _SCORE_RE.search(text)
        if m:
            return int(m.group(1)), int(m.group(2)), "final"

        return None, None, "scheduled"

    # ------------------------------------------------------------------
    # Competition parsing
    # ------------------------------------------------------------------

    def _parse_competition(self, row: ElementHandle) -> str:
        """Extract competition name from the competition column."""
        col = row.query_selector(_COL_COMPETITION)
        if not col:
            return "MLS Next"

        text = (col.text_content() or "").strip()
        if not text:
            return "MLS Next"

        return " ".join(text.split())  # collapse whitespace

    # ------------------------------------------------------------------
    # Date helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _looks_like_date(s: str) -> bool:
        """Return True if the string contains a date-like pattern."""
        return any(p.search(s) for p in _DATE_PATTERNS)

    @staticmethod
    def _to_iso_date(raw: str) -> str | None:
        """Convert a date string to YYYY-MM-DD ISO format."""
        # MM/DD/YYYY
        m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", raw)
        if m:
            month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return f"{year:04d}-{month:02d}-{day:02d}"

        # MM/DD/YY
        m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2})$", raw)
        if m:
            month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
            year = year + 2000 if year < 50 else year + 1900
            return f"{year:04d}-{month:02d}-{day:02d}"

        # YYYY-MM-DD (already ISO)
        m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", raw)
        if m:
            year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return f"{year:04d}-{month:02d}-{day:02d}"

        return None

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _text(parent: ElementHandle, selector: str) -> str | None:
        """Query a selector and return stripped text content, or None."""
        el = parent.query_selector(selector)
        if not el:
            return None
        text = el.text_content()
        return text.strip() if text else None
