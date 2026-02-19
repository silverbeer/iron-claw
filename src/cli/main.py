"""iron-claw CLI — RADIUS-controlled LLM match scraper."""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv

from radius.client import AuthenticationError, RadiusSessionClient
from radius.models import RadiusConfig
from utils.logger import configure_logging


def _resolve_password(password: str | None) -> str:
    """Resolve password: CLI flag → RADIUS_PASSWORD env var → interactive prompt."""
    if password:
        return password
    env_val = os.environ.get("RADIUS_PASSWORD")
    if env_val:
        return env_val
    return typer.prompt("Password", hide_input=True)


app = typer.Typer(
    name="iron-claw",
    help="RADIUS-controlled LLM match scraper for MLS Next matches.",
    no_args_is_help=True,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@app.callback()
def main(
    json_logs: Annotated[
        bool, typer.Option("--json-logs", help="Output structured JSON logs")
    ] = False,
    env: Annotated[
        str, typer.Option("--env", help="Environment name (loads .env.<name>)")
    ] = "local",
) -> None:
    """Configure global options."""
    env_file = PROJECT_ROOT / f".env.{env}"
    if env_file.exists():
        load_dotenv(env_file, override=True)
        typer.echo(f"Loaded {env_file.name}")
    else:
        typer.echo(f"Warning: {env_file} not found", err=True)
    configure_logging(json_output=json_logs)


@app.command()
def auth_test(
    username: Annotated[str, typer.Option(help="RADIUS username")] = "iron-claw-scraper",
    password: Annotated[
        str | None, typer.Option(help="RADIUS password (default: $RADIUS_PASSWORD)")
    ] = None,
    server: Annotated[str, typer.Option(help="RADIUS server")] = "localhost",
    secret: Annotated[str, typer.Option(help="RADIUS shared secret")] = "testing123",
) -> None:
    """Test RADIUS authentication and display granted attributes."""
    password = _resolve_password(password)
    config = RadiusConfig(server=server, secret=secret)
    client = RadiusSessionClient(config)

    try:
        grant = client.authenticate(username, password)
    except AuthenticationError:
        typer.echo("Access-Reject: authentication failed", err=True)
        raise typer.Exit(code=1) from None

    typer.echo("Access-Accept received!")
    typer.echo(f"  Session Timeout:  {grant.session_timeout}s")
    typer.echo(f"  Token Budget:     {grant.token_budget:,}")
    typer.echo(f"  Model Allowed:    {grant.model_allowed}")
    typer.echo(f"  Max Pages:        {grant.max_pages}")
    typer.echo(f"  Max LLM Calls:    {grant.max_llm_calls}")
    typer.echo(f"  Allowed Domains:  {grant.allowed_domains}")
    typer.echo(f"  Output Queue:     {grant.output_queue}")
    typer.echo(f"  Monthly Budget:   {grant.monthly_budget:,}")
    typer.echo(f"  Monthly Used:     {grant.monthly_used:,}")


@app.command()
def scrape(
    username: Annotated[str, typer.Option(help="RADIUS username")] = "iron-claw-scraper",
    password: Annotated[
        str | None, typer.Option(help="RADIUS password (default: $RADIUS_PASSWORD)")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Use test model (no API calls)")
    ] = False,
    server: Annotated[str, typer.Option(help="RADIUS server")] = "localhost",
    secret: Annotated[str, typer.Option(help="RADIUS shared secret")] = "testing123",
    target_url: Annotated[
        str | None, typer.Option(help="URL to scrape (default: MLS Next schedule)")
    ] = None,
    age_group: Annotated[str, typer.Option(help="MLS Next age group (U13-U19)")] = "U14",
    division: Annotated[str, typer.Option(help="MLS Next division")] = "Northeast",
    look_back_days: Annotated[
        int, typer.Option(help="Number of days back from today for date range")
    ] = 7,
    start_date: Annotated[
        str | None, typer.Option(help="Start date YYYY-MM-DD (overrides --look-back-days)")
    ] = None,
    end_date: Annotated[
        str | None, typer.Option(help="End date YYYY-MM-DD (default: today)")
    ] = None,
    headless: Annotated[bool, typer.Option(help="Run browser in headless mode")] = True,
) -> None:
    """Run the match scraper with RADIUS session control."""
    from scraper.engine import ScrapingEngine
    from scraper.playwright_fetcher import ScrapeConfig

    password = _resolve_password(password)

    if start_date:
        sd = date.fromisoformat(start_date)
    else:
        sd = date.today() - timedelta(days=look_back_days)
    ed = date.fromisoformat(end_date) if end_date else date.today()

    scrape_config = ScrapeConfig(
        age_group=age_group,
        division=division,
        start_date=sd,
        end_date=ed,
        headless=headless,
    )

    config = RadiusConfig(server=server, secret=secret)
    engine = ScrapingEngine(config=config, dry_run=dry_run, scrape_config=scrape_config)

    try:
        result = engine.run(username=username, password=password, target_url=target_url)
    except AuthenticationError:
        typer.echo("Access-Reject: cannot start scraping session", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(f"Session complete: {result.matches_found} matches found")
    typer.echo(f"  Pages visited: {result.pages_visited}")
    typer.echo(f"  Queued:        {len(result.queued)}")

    typer.echo("")
    for m in result.matches:
        score = f"{m.home_score}-{m.away_score}" if m.home_score is not None else "TBD"
        typer.echo(f"  [{m.date}] {m.home_team} vs {m.away_team}  {score}  ({m.status})")

    sys.exit(0 if result.matches_found > 0 else 1)


@app.command()
def proxy(
    port: Annotated[int | None, typer.Option(help="Port to listen on")] = None,
    host: Annotated[str | None, typer.Option(help="Host to bind to")] = None,
    username: Annotated[
        str | None, typer.Option(help="RADIUS username (enables RADIUS auth)")
    ] = None,
    password: Annotated[
        str | None, typer.Option(help="RADIUS password (default: $RADIUS_PASSWORD)")
    ] = None,
    server: Annotated[str | None, typer.Option(help="RADIUS server")] = None,
    secret: Annotated[str | None, typer.Option(help="RADIUS shared secret")] = None,
) -> None:
    """Start the LLM proxy server (forwards to Anthropic API)."""
    import uvicorn

    from proxy.config import ProxyConfig
    from proxy.server import create_app

    # Build ProxyConfig — only pass CLI args that were explicitly provided,
    # so pydantic-settings can resolve env vars (PROXY_HOST, PROXY_PORT, etc.)
    proxy_overrides: dict = {}
    if port is not None:
        proxy_overrides["port"] = port
    if host is not None:
        proxy_overrides["host"] = host

    config = ProxyConfig(**proxy_overrides)

    if not config.anthropic_api_key:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            typer.echo("Error: ANTHROPIC_API_KEY or PROXY_ANTHROPIC_API_KEY required", err=True)
            raise typer.Exit(code=1)
        config = ProxyConfig(anthropic_api_key=api_key, **proxy_overrides)

    # RADIUS auth: CLI --username > IRON_CLAW_USERNAME env var
    if username is None:
        username = os.environ.get("IRON_CLAW_USERNAME")

    radius_config = None
    if username:
        password = _resolve_password(password)
        radius_overrides: dict = {}
        if server is not None:
            radius_overrides["server"] = server
        if secret is not None:
            radius_overrides["secret"] = secret
        radius_config = RadiusConfig(**radius_overrides)

    _app = create_app(
        config,
        radius_config=radius_config,
        username=username,
        password=password,
    )
    typer.echo(f"Starting iron-claw proxy on {config.host}:{config.port}")
    uvicorn.run(_app, host=config.host, port=config.port, log_level="warning")


@app.command()
def status(
    server: Annotated[str, typer.Option(help="RADIUS server")] = "localhost",
    secret: Annotated[str, typer.Option(help="RADIUS shared secret")] = "testing123",
) -> None:
    """Show current session and budget status (queries radacct)."""
    typer.echo("Status command not yet implemented (requires direct DB query)")
    raise typer.Exit(code=0)


if __name__ == "__main__":
    app()
