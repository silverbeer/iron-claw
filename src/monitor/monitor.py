"""iron-claw proxy log monitor — real-time TUI using Rich.

Parses structlog JSON lines from a file (follow mode) or stdin and renders a
live split-panel dashboard: colorised event log on the right, running session
statistics on the left.

Usage::

    # Follow a log file
    iron-claw monitor /var/log/iron-claw.json

    # Pipe from kubectl / docker
    kubectl logs -f deploy/iron-claw-proxy | iron-claw monitor

    # Pipe from docker compose
    docker compose logs -f iron-claw-proxy | iron-claw monitor
"""

from __future__ import annotations

import json
import logging
import sys
import time
from collections import deque
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# ── Suppress structlog / stdlib logging so it doesn't bleed into the TUI ──────
logging.disable(logging.CRITICAL)


# ── Event → category mapping ─────────────────────────────────────────────────

#: (label, color) for each log event prefix
CATEGORY_LABELS: dict[str, tuple[str, str]] = {
    "radius": ("AUTH  ", "bright_green"),
    "proxy": ("PROXY ", "bright_blue"),
    "policy": ("POLICY", "bright_yellow"),
    "scraper": ("SCRPR ", "bright_cyan"),
    "queue": ("QUEUE ", "bright_magenta"),
}

#: Per-event Rich style overrides
EVENT_STYLE: dict[str, str] = {
    "radius.auth.accepted": "bold bright_green",
    "radius.auth.rejected": "bold bright_red",
    "radius.acct.start": "green",
    "radius.acct.interim": "dim green",
    "radius.acct.stop": "dim yellow",
    "proxy.radius.ready": "bold bright_green",
    "proxy.request": "bright_blue",
    "proxy.response": "cyan",
    "proxy.rejected": "bold red",
    "proxy.downgrade": "bold yellow",
    "proxy.warning": "dark_orange3",
    "proxy.radius.stopped": "dim white",
    "policy.throttle": "bold yellow",
    "policy.monitor": "dim yellow",
    "policy.no_rule_matched": "dim yellow",
    "scraper.page_complete": "bright_green",
    "scraper.budget_exceeded": "bold red",
    "scraper.max_pages_reached": "yellow",
    "scraper.pages_reduced": "yellow",
    "scraper.extraction_error": "red",
    "scraper.queue_error": "red",
    "scraper.error": "bold red",
    "queue.connected": "magenta",
    "queue.submitted": "bright_magenta",
    "queue.disconnected": "dim magenta",
}

LEVEL_STYLES: dict[str, str] = {
    "debug": "dim white",
    "info": "white",
    "warning": "yellow",
    "error": "bold red",
    "critical": "bold bright_red",
}

ACTION_STYLES: dict[str, str] = {
    "DOWNGRADE_MODEL": "yellow",
    "REDUCE_PAGES": "dark_orange3",
    "KILL_SESSION": "bold red",
}

# Fields that are shown in the stats panel or are purely internal — skip them
# in the inline field display so we don't double-render.
_SKIP_FIELDS = frozenset({"event", "level", "timestamp", "logger", "_record", "exc_info"})
_SESSION_FIELDS = frozenset({"username", "session_id", "token_budget", "model_allowed"})


# ── Helpers ──────────────────────────────────────────────────────────────────


def _category(event: str) -> tuple[str, str]:
    prefix = event.split(".")[0] if "." in event else "other"
    return CATEGORY_LABELS.get(prefix, ("OTHER ", "white"))


def _event_style(event: str, record: dict) -> str:
    if record.get("level") in ("error", "critical"):
        return "bold red"
    return EVENT_STYLE.get(event, "white")


def _format_extra(record: dict) -> Text:
    """Render interesting extra fields as compact colourised key=value pairs."""
    text = Text()
    for k, v in record.items():
        if k in _SKIP_FIELDS:
            continue
        if k == "budget_pct" and isinstance(v, (int, float)):
            pct = float(v)
            color = "red" if pct >= 90 else "yellow" if pct >= 75 else "green"
            text.append(f" {k}=", style="dim")
            text.append(f"{pct:.0f}%", style=f"bold {color}")
        elif k == "action" and isinstance(v, str):
            text.append(f" {k}=", style="dim")
            text.append(str(v), style=ACTION_STYLES.get(v, "yellow"))
        elif k in ("input_tokens", "output_tokens", "tokens_used", "token_budget"):
            text.append(f" {k}=", style="dim")
            text.append(f"{int(v):,}" if isinstance(v, (int, float)) else str(v), style="cyan")
        elif k == "status" and isinstance(v, (int, str)):
            try:
                code = int(v)
                color = "green" if code < 400 else "red"
            except ValueError:
                color = "white"
            text.append(" status=", style="dim")
            text.append(str(v), style=color)
        elif k == "model" and isinstance(v, str):
            short = v.replace("claude-", "").replace("-latest", "")
            text.append(" model=", style="dim")
            text.append(short, style="bright_blue")
        elif isinstance(v, bool):
            text.append(f" {k}=", style="dim")
            text.append(str(v).lower(), style="white")
        else:
            text.append(f" {k}=", style="dim")
            text.append(str(v), style="dim white")
    return text


def _parse_line(raw: str) -> dict | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def _render_log_line(record: dict) -> Text:
    """Render a single structlog JSON record as a Rich Text line."""
    event = str(record.get("event", "unknown"))
    ts_raw = str(record.get("timestamp", ""))

    # Timestamp → HH:MM:SS
    try:
        dt = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        ts = dt.strftime("%H:%M:%S")
    except (ValueError, AttributeError):
        ts = (ts_raw[:8] if ts_raw else "??:??:??").ljust(8)

    cat_label, cat_color = _category(event)
    ev_style = _event_style(event, record)

    line = Text(overflow="fold")
    line.append(f"{ts} ", style="dim white")
    line.append(f"[{cat_label}] ", style=f"bold {cat_color}")
    line.append(event, style=ev_style)
    extra = _format_extra(record)
    if extra:
        line.append_text(extra)
    return line


# ── State tracker ─────────────────────────────────────────────────────────────


class MonitorState:
    """Accumulates statistics by processing each parsed log record."""

    def __init__(self) -> None:
        self.monitor_start = time.monotonic()

        # Session (populated from RADIUS events)
        self.session_username: str | None = None
        self.session_id: str | None = None
        self.token_budget: int = 0
        self.tokens_used: int = 0
        self.session_start: float | None = None
        self.session_active: bool = False

        # LLM / proxy
        self.last_model: str | None = None
        self.llm_calls: int = 0
        self.total_requests: int = 0
        self.total_responses: int = 0
        self.total_rejected: int = 0
        self.total_downgrades: int = 0

        # Scraper / queue
        self.total_pages: int = 0
        self.total_matches: int = 0
        self.total_queued: int = 0

        # Policy
        self.policy_mode: str | None = None
        self.throttle_actions: dict[str, int] = {}
        self.monitor_actions: dict[str, int] = {}

        # Auth totals
        self.auth_accepts: int = 0
        self.auth_rejects: int = 0

    # ------------------------------------------------------------------

    def update(self, event: str, record: dict) -> None:
        match event:
            case "radius.auth.accepted":
                self.session_username = record.get("username")
                self.token_budget = int(record.get("token_budget", 0))
                self.auth_accepts += 1
                self.session_start = time.monotonic()
                self.session_active = True

            case "radius.auth.rejected":
                self.auth_rejects += 1

            case "radius.acct.start":
                self.session_id = record.get("session_id")

            case "radius.acct.interim":
                self.tokens_used = int(record.get("tokens_used", self.tokens_used))

            case "radius.acct.stop":
                self.tokens_used = int(record.get("tokens_used", self.tokens_used))
                self.session_active = False

            case "proxy.radius.ready":
                self.token_budget = int(record.get("token_budget", self.token_budget))
                if m := record.get("model_allowed"):
                    self.last_model = m

            case "proxy.request":
                self.total_requests += 1
                self.llm_calls += 1
                if m := record.get("model"):
                    self.last_model = m

            case "proxy.response":
                self.total_responses += 1
                inp = int(record.get("input_tokens", 0))
                out = int(record.get("output_tokens", 0))
                self.tokens_used += inp + out
                if m := record.get("model"):
                    self.last_model = m

            case "proxy.rejected":
                self.total_rejected += 1

            case "proxy.downgrade":
                self.total_downgrades += 1
                if m := record.get("downgraded_to"):
                    self.last_model = m

            case "policy.throttle":
                action = str(record.get("action", "UNKNOWN"))
                self.throttle_actions[action] = self.throttle_actions.get(action, 0) + 1

            case "policy.monitor":
                self.policy_mode = "monitor"
                action = str(record.get("action", "UNKNOWN"))
                self.monitor_actions[action] = self.monitor_actions.get(action, 0) + 1

            case "scraper.page_complete":
                self.total_pages += 1
                self.total_matches += int(record.get("matches", 0))

            case "queue.submitted":
                self.total_queued += int(record.get("count", 0))


# ── Panel renderers ───────────────────────────────────────────────────────────


def _budget_bar(used: int, total: int, width: int = 16) -> Text:
    pct = min(used / total, 1.0) if total else 0.0
    color = "red" if pct >= 0.9 else "yellow" if pct >= 0.75 else "green"
    filled = int(pct * width)
    bar = Text()
    bar.append("█" * filled, style=color)
    bar.append("░" * (width - filled), style="dim")
    return bar


def _elapsed(seconds: float) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _make_stats_panel(state: MonitorState) -> Panel:
    g = Table.grid(padding=(0, 1))
    g.add_column(style="dim", no_wrap=True, min_width=9)
    g.add_column(no_wrap=True)

    # ── Session ──────────────────────────────────────────────────────────────
    if state.session_username:
        g.add_row("User", f"[bold]{state.session_username}[/]")
    if state.session_id:
        sid = state.session_id
        sid_display = sid[:12] + "…" if len(sid) > 13 else sid
        g.add_row("Session", f"[dim]{sid_display}[/]")

    if state.session_username:
        if state.session_active:
            g.add_row("Status", "[bold green]● ACTIVE[/]")
        else:
            g.add_row("Status", "[dim]○ ended[/]")

    if state.last_model:
        short = state.last_model.replace("claude-", "").replace("-latest", "")
        g.add_row("Model", f"[bright_blue]{short}[/]")

    if state.session_start is not None:
        elapsed = time.monotonic() - state.session_start
        g.add_row("Elapsed", f"[dim]{_elapsed(elapsed)}[/]")

    # ── Token budget bar ─────────────────────────────────────────────────────
    if state.token_budget > 0:
        pct = min(state.tokens_used / state.token_budget, 1.0)
        color = "red" if pct >= 0.9 else "yellow" if pct >= 0.75 else "green"
        g.add_row("", "")
        g.add_row("Budget", _budget_bar(state.tokens_used, state.token_budget))
        used_str = f"[cyan]{state.tokens_used:,}[/] [dim]/ {state.token_budget:,}[/]"
        g.add_row("", Text.from_markup(f"{used_str}  [bold {color}]{pct * 100:.0f}%[/]"))
    elif state.tokens_used:
        g.add_row("Tokens", f"[cyan]{state.tokens_used:,}[/]")

    # ── Counters ─────────────────────────────────────────────────────────────
    g.add_row("", "")
    g.add_row("[dim]Requests[/]", f"[bright_blue]{state.total_requests}[/]")
    g.add_row("[dim]Responses[/]", f"[cyan]{state.total_responses}[/]")
    if state.total_rejected:
        g.add_row("[dim]Rejected[/]", f"[bold red]{state.total_rejected}[/]")
    if state.total_downgrades:
        g.add_row("[dim]Downgrades[/]", f"[bold yellow]{state.total_downgrades}[/]")
    g.add_row("[dim]Pages[/]", f"[bright_green]{state.total_pages}[/]")
    g.add_row("[dim]Matches[/]", f"[bright_green]{state.total_matches}[/]")
    if state.total_queued:
        g.add_row("[dim]Queued[/]", f"[magenta]{state.total_queued}[/]")

    # ── Policy ────────────────────────────────────────────────────────────────
    if state.throttle_actions or state.monitor_actions:
        g.add_row("", "")
        mode_label = f" [dim]({state.policy_mode})[/]" if state.policy_mode else ""
        g.add_row(f"[dim]── Policy[/]{mode_label}", "")
        for action, count in sorted(state.throttle_actions.items()):
            style = ACTION_STYLES.get(action, "yellow")
            label = action.replace("_", " ").title()
            g.add_row(f"[dim]{label}[/]", f"[{style}]{count}[/]")
        for action, count in sorted(state.monitor_actions.items()):
            label = action.replace("_", " ").title()
            g.add_row(f"[dim]{label}[/]", f"[dim yellow]{count} (skipped)[/]")

    # ── Auth totals ──────────────────────────────────────────────────────────
    g.add_row("", "")
    g.add_row("[dim]── Auth[/]", "")
    g.add_row("[dim]Accepts[/]", f"[green]{state.auth_accepts}[/]")
    if state.auth_rejects:
        g.add_row("[dim]Rejects[/]", f"[bold red]{state.auth_rejects}[/]")

    # ── Monitor uptime ───────────────────────────────────────────────────────
    g.add_row("", "")
    uptime = _elapsed(time.monotonic() - state.monitor_start)
    g.add_row("[dim]Uptime[/]", f"[dim]{uptime}[/]")

    return Panel(
        g, title="[bold bright_blue]SESSION[/]", border_style="bright_blue", padding=(1, 1)
    )


def _make_log_panel(lines: deque[Text]) -> Panel:
    body = Text(overflow="fold")
    for i, line in enumerate(lines):
        if i:
            body.append("\n")
        body.append_text(line)
    return Panel(body, title="[bold]LIVE LOG[/]", border_style="dim blue", padding=(0, 1))


def _make_header() -> Text:
    now = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
    t = Text(justify="right", overflow="fold")
    t.append("iron-claw ", style="bold bright_blue")
    t.append("monitor", style="bold white")
    t.append(f"  ·  {now}", style="dim")
    t.append("  [Ctrl-C to quit]", style="dim")
    return t


# ── Main monitor class ────────────────────────────────────────────────────────


class LogMonitor:
    """Drives the live TUI: reads log lines, updates state, re-renders."""

    def __init__(
        self,
        log_file: Path | None = None,
        max_log_lines: int = 200,
        from_start: bool = False,
    ) -> None:
        self.log_file = log_file
        self.max_log_lines = max_log_lines
        self.from_start = from_start
        self.state = MonitorState()
        self.log_lines: deque[Text] = deque(maxlen=max_log_lines)
        self._console = Console()

    # ------------------------------------------------------------------

    def _line_source(self) -> Iterator[str]:
        if self.log_file:
            with open(self.log_file) as fh:
                if not self.from_start:
                    fh.seek(0, 2)  # jump to end — tail behaviour
                while True:
                    line = fh.readline()
                    if line:
                        yield line
                    else:
                        time.sleep(0.05)
        else:
            for line in sys.stdin:
                yield line

    def _build_layout(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=1),
            Layout(name="body"),
        )
        layout["body"].split_row(
            Layout(name="stats", ratio=1, minimum_size=28),
            Layout(name="logs", ratio=3),
        )
        return layout

    # ------------------------------------------------------------------

    def run(self) -> None:
        layout = self._build_layout()

        with Live(
            layout,
            console=self._console,
            refresh_per_second=4,
            screen=True,
        ):
            try:
                for raw in self._line_source():
                    record = _parse_line(raw)
                    if record is None:
                        # Non-JSON line — show as-is in dim style
                        stripped = raw.strip()
                        if stripped:
                            self.log_lines.append(Text(stripped, style="dim"))
                    else:
                        event = str(record.get("event", ""))
                        self.state.update(event, record)
                        self.log_lines.append(_render_log_line(record))

                    layout["header"].update(_make_header())
                    layout["stats"].update(_make_stats_panel(self.state))
                    layout["logs"].update(_make_log_panel(self.log_lines))

            except KeyboardInterrupt:
                pass
