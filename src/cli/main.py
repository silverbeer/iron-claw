"""iron-claw CLI — RADIUS-controlled LLM match scraper."""

from __future__ import annotations

import sys
from typing import Annotated

import typer

from radius.client import AuthenticationError, RadiusSessionClient
from radius.models import RadiusConfig
from utils.logger import configure_logging

app = typer.Typer(
    name="iron-claw",
    help="RADIUS-controlled LLM match scraper for MLS Next matches.",
    no_args_is_help=True,
)


@app.callback()
def main(
    json_logs: Annotated[
        bool, typer.Option("--json-logs", help="Output structured JSON logs")
    ] = False,
) -> None:
    """Configure global options."""
    configure_logging(json_output=json_logs)


@app.command()
def auth_test(
    username: Annotated[str, typer.Option(help="RADIUS username")] = "iron-claw-scraper",
    password: Annotated[
        str, typer.Option(help="RADIUS password", prompt=True, hide_input=True)
    ] = "",
    server: Annotated[str, typer.Option(help="RADIUS server")] = "localhost",
    secret: Annotated[str, typer.Option(help="RADIUS shared secret")] = "testing123",
) -> None:
    """Test RADIUS authentication and display granted attributes."""
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
        str, typer.Option(help="RADIUS password", prompt=True, hide_input=True)
    ] = "",
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Use mock LLM provider")] = False,
    server: Annotated[str, typer.Option(help="RADIUS server")] = "localhost",
    secret: Annotated[str, typer.Option(help="RADIUS shared secret")] = "testing123",
    target_url: Annotated[
        str | None, typer.Option(help="URL to scrape (default: MLS Next schedule)")
    ] = None,
) -> None:
    """Run the LLM-powered match scraper with RADIUS session control."""
    from scraper.engine import ScrapingEngine

    config = RadiusConfig(server=server, secret=secret)
    engine = ScrapingEngine(config=config, dry_run=dry_run)

    try:
        result = engine.run(username=username, password=password, target_url=target_url)
    except AuthenticationError:
        typer.echo("Access-Reject: cannot start scraping session", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(f"Session complete: {result.matches_found} matches found")
    typer.echo(f"  Tokens used:  {result.tokens_used:,}")
    typer.echo(f"  Pages visited: {result.pages_visited}")
    typer.echo(f"  LLM calls:    {result.llm_calls_made}")
    sys.exit(0 if result.matches_found > 0 else 1)


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
