# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**iron-claw** is a RADIUS-controlled LLM match scraper that uses AI to parse MLS Next match data from web pages. FreeRADIUS provides the metering and control layer: authenticating the scraper, authorizing token budgets and model tiers, tracking consumption via accounting, and enforcing throttling when budgets are exceeded.

## Architecture

- **RADIUS server:** FreeRADIUS 3.2.x in Docker (extends `ghcr.io/silverbeer/freeradius-lab:latest`)
- **SQL backend:** Supabase PostgreSQL (`rlm_sql_postgresql`)
- **LLM provider:** Anthropic Claude API (with protocol for future providers)
- **Message queue:** RabbitMQ (submits matches to missing-table Celery workers)
- **Custom RADIUS dictionary:** Vendor MissTable (ID: 99901) with VSAs for token budgets, model control, page limits
- **Deployment:** K3s CronJob

## Key Technology Choices

| Tool | Purpose |
|------|---------|
| Python >= 3.12 + uv | Package management |
| Typer | CLI framework (`iron-claw scrape`, `auth-test`, `status`) |
| pyrad | Python RADIUS client library |
| Pydantic v2 | Data models and settings |
| httpx | HTTP client for page fetching |
| anthropic | Claude API SDK |
| Ruff | Linting and formatting |
| pytest | Test framework |

## Common Commands

### Docker (FreeRADIUS)
```bash
cd docker && docker compose up -d    # Start FreeRADIUS
cd docker && docker compose down     # Stop FreeRADIUS
```

### CLI
```bash
uv run iron-claw scrape --dry-run    # Dry run with mock provider
uv run iron-claw auth-test           # Test RADIUS authentication
uv run iron-claw status              # Show session/budget status
```

### Testing
```bash
cd tests && uv run pytest                          # All tests
cd tests && uv run pytest test_auth.py             # Auth tests only
cd tests && uv run pytest test_accounting.py       # Accounting tests only
cd tests && uv run pytest -k "test_valid"          # Filter by name
```

### FreeRADIUS
```bash
radiusd -X          # Debug mode (foreground, verbose)
radiusd -C          # Verify config syntax
radtest iron-claw-scraper <password> localhost 0 testing123
```

## Repo Layout

- `docker/` — Dockerfile + docker-compose for FreeRADIUS with PostgreSQL module
- `raddb/` — FreeRADIUS config overlay (mounted into container)
- `src/cli/` — Typer CLI application
- `src/radius/` — RADIUS client wrapper (pyrad), models, dictionary
- `src/scraper/` — Scraping engine, page fetcher
- `src/llm/` — LLM provider protocol + implementations (Anthropic, mock)
- `src/models/` — Pydantic data models (session, match data)
- `src/policy/` — Throttling policy engine
- `src/queue/` — RabbitMQ client for match submission
- `src/utils/` — Logger, metrics
- `tests/` — pytest test suite with pyrad fixtures
- `k3s/` — K3s CronJob manifests
- `dashboards/` — Grafana dashboard JSON models
- `terraform/grafana/` — Terraform IaC for dashboards and alerts
- `.github/workflows/` — CI pipelines

## Design Conventions

- Pydantic v2 for all data models (use `model_validate`, not `parse_obj`)
- `from __future__ import annotations` in all Python files
- Ruff for linting and formatting (line length 99)
- Type hints on all public functions
- No default exports; use explicit imports
