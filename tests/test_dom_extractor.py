"""Unit tests for DOMExtractor — deterministic match extraction via CSS selectors.

Uses mock Playwright ElementHandle/Frame objects with real MLS Next HTML structure.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from scraper.dom_extractor import DOMExtractor

# ---------------------------------------------------------------------------
# HTML fixture — minimal but structurally faithful MLS Next Bootstrap grid
# ---------------------------------------------------------------------------

MATCH_ROW_HTML = """\
<div class="container-fluid container-table-matches">
  <div class="container-row">
    <div class="row table-content-row hidden-xs">
      <div class="col-sm-1 pad-0">99963\t\t\t\n\t\t\tMALE</div>
      <div class="col-sm-2">
        02/28/2026\n3:00 PM\nMetLife Stadium
      </div>
      <div class="col-sm-1 pad-0">U14</div>
      <div class="col-sm-2">MLS Next\nNortheast</div>
      <div class="col-sm-6 pad-0">
        <div class="container-teams-info">
          <div class="container-first-team"><p>IFA Warriors</p></div>
          <div class="container-score"><span class="score-match-table">2 - 1</span></div>
          <div class="container-second-team"><p>FC Dallas</p></div>
        </div>
      </div>
    </div>

    <div class="row table-content-row hidden-xs">
      <div class="col-sm-1 pad-0">99964\t\t\t\n\t\t\tMALE</div>
      <div class="col-sm-2">
        03/01/2026\n10:00 AM\nRed Bull Arena
      </div>
      <div class="col-sm-1 pad-0">U14</div>
      <div class="col-sm-2">MLS Next\nNortheast</div>
      <div class="col-sm-6 pad-0">
        <div class="container-teams-info">
          <div class="container-first-team"><p>NYCFC Academy</p></div>
          <div class="container-score"><span class="score-match-table">VS</span></div>
          <div class="container-second-team"><p>Philadelphia Union</p></div>
        </div>
      </div>
    </div>

    <div class="row table-content-row hidden-xs">
      <div class="col-sm-1 pad-0">99965\n\t\t\tMALE</div>
      <div class="col-sm-2">
        03/02/2026\n1:30 PM\nSubaru Park
      </div>
      <div class="col-sm-1 pad-0">U14</div>
      <div class="col-sm-2">MLS Next\nNortheast</div>
      <div class="col-sm-6 pad-0">
        <div class="container-teams-info">
          <div class="container-first-team"><p>Revolution Academy</p></div>
          <div class="container-score"><span class="score-match-table">0 - 0</span></div>
          <div class="container-second-team"><p>Inter Miami CF</p></div>
        </div>
      </div>
    </div>
  </div>
</div>
"""

NO_MATCHES_HTML = """\
<div class="container-fluid container-table-matches">
  <div class="no-results">No matches found</div>
</div>
"""

TWO_DIGIT_YEAR_HTML = """\
<div class="container-fluid container-table-matches">
  <div class="container-row">
    <div class="row table-content-row hidden-xs">
      <div class="col-sm-1 pad-0">10001</div>
      <div class="col-sm-2">
        09/20/25\n03:45 PM\nSomeField
      </div>
      <div class="col-sm-1 pad-0">U14</div>
      <div class="col-sm-2">MLS Next</div>
      <div class="col-sm-6 pad-0">
        <div class="container-teams-info">
          <div class="container-first-team"><p>Team A</p></div>
          <div class="container-score"><span class="score-match-table">TBD</span></div>
          <div class="container-second-team"><p>Team B</p></div>
        </div>
      </div>
    </div>
  </div>
</div>
"""


# ---------------------------------------------------------------------------
# Mock helpers — simulate Playwright's sync_api objects from real HTML
# ---------------------------------------------------------------------------


def _make_frame(html: str) -> MagicMock:
    """Build a mock Frame backed by BeautifulSoup for CSS selector queries.

    We use BeautifulSoup to resolve CSS selectors so the test fixtures
    are validated against real HTML structure, not just hardcoded return values.
    """
    from bs4 import BeautifulSoup, Tag

    soup = BeautifulSoup(html, "html.parser")

    def _wrap_tag(tag: Tag | None) -> MagicMock | None:
        if tag is None:
            return None
        el = MagicMock()
        el.text_content.return_value = tag.get_text()

        def _qs(sel: str) -> MagicMock | None:
            child = tag.select_one(sel)
            return _wrap_tag(child)

        def _qsa(sel: str) -> list[MagicMock]:
            children = tag.select(sel)
            return [_wrap_tag(c) for c in children]

        el.query_selector = MagicMock(side_effect=_qs)
        el.query_selector_all = MagicMock(side_effect=_qsa)
        return el

    frame = MagicMock()

    def frame_qs(sel: str) -> MagicMock | None:
        tag = soup.select_one(sel)
        return _wrap_tag(tag)

    def frame_qsa(sel: str) -> list[MagicMock]:
        tags = soup.select(sel)
        return [_wrap_tag(t) for t in tags]

    frame.query_selector = MagicMock(side_effect=frame_qs)
    frame.query_selector_all = MagicMock(side_effect=frame_qsa)
    return frame


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDOMExtractor:
    def setup_method(self):
        self.extractor = DOMExtractor()

    def test_extract_three_matches(self):
        frame = _make_frame(MATCH_ROW_HTML)
        matches = self.extractor.extract(frame)

        assert len(matches) == 3

    def test_first_match_teams(self):
        frame = _make_frame(MATCH_ROW_HTML)
        matches = self.extractor.extract(frame)

        assert matches[0].home_team == "IFA Warriors"
        assert matches[0].away_team == "FC Dallas"

    def test_first_match_score_final(self):
        frame = _make_frame(MATCH_ROW_HTML)
        matches = self.extractor.extract(frame)

        assert matches[0].home_score == 2
        assert matches[0].away_score == 1
        assert matches[0].status == "final"

    def test_first_match_date_iso(self):
        frame = _make_frame(MATCH_ROW_HTML)
        matches = self.extractor.extract(frame)

        assert matches[0].date == "2026-02-28"

    def test_first_match_venue(self):
        frame = _make_frame(MATCH_ROW_HTML)
        matches = self.extractor.extract(frame)

        assert matches[0].venue == "MetLife Stadium"

    def test_scheduled_match_vs(self):
        """'VS' score text → status=scheduled, scores=None."""
        frame = _make_frame(MATCH_ROW_HTML)
        matches = self.extractor.extract(frame)

        nycfc = matches[1]
        assert nycfc.home_team == "NYCFC Academy"
        assert nycfc.away_team == "Philadelphia Union"
        assert nycfc.status == "scheduled"
        assert nycfc.home_score is None
        assert nycfc.away_score is None

    def test_zero_zero_draw_is_final(self):
        """0-0 is a real score, not TBD."""
        frame = _make_frame(MATCH_ROW_HTML)
        matches = self.extractor.extract(frame)

        draw = matches[2]
        assert draw.home_score == 0
        assert draw.away_score == 0
        assert draw.status == "final"

    def test_competition_extracted(self):
        frame = _make_frame(MATCH_ROW_HTML)
        matches = self.extractor.extract(frame)

        assert "MLS Next" in matches[0].competition

    def test_no_rows_returns_empty(self):
        frame = _make_frame(NO_MATCHES_HTML)
        matches = self.extractor.extract(frame)

        assert matches == []

    def test_two_digit_year(self):
        """MM/DD/YY date format parsed correctly."""
        frame = _make_frame(TWO_DIGIT_YEAR_HTML)
        matches = self.extractor.extract(frame)

        assert len(matches) == 1
        assert matches[0].date == "2025-09-20"
        assert matches[0].status == "scheduled"

    def test_time_extracted(self):
        frame = _make_frame(MATCH_ROW_HTML)
        matches = self.extractor.extract(frame)

        assert matches[0].time == "3:00 PM"


class TestToIsoDate:
    """Unit tests for the static _to_iso_date helper."""

    def test_mm_dd_yyyy(self):
        assert DOMExtractor._to_iso_date("02/28/2026") == "2026-02-28"

    def test_mm_dd_yy(self):
        assert DOMExtractor._to_iso_date("09/20/25") == "2025-09-20"

    def test_iso_passthrough(self):
        assert DOMExtractor._to_iso_date("2026-03-01") == "2026-03-01"

    def test_garbage_returns_none(self):
        assert DOMExtractor._to_iso_date("not-a-date") is None

    def test_single_digit_month_day(self):
        assert DOMExtractor._to_iso_date("1/5/2026") == "2026-01-05"
