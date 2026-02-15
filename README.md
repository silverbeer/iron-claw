# iron-claw

RADIUS-controlled LLM match scraper. Uses FreeRADIUS to authenticate, authorize token budgets, and track LLM consumption while scraping MLS Next match data with AI.

## Quick Start

```bash
# Start FreeRADIUS
cd docker && docker compose up -d

# Test authentication
uv run iron-claw auth-test

# Run scraper (dry run)
uv run iron-claw scrape --dry-run
```

## Architecture

```
iron-claw CLI
  ├── Access-Request  ──→  FreeRADIUS (Docker)
  │                            └── rlm_sql_postgresql ──→ Supabase
  ├── Acct-Start      ──→  radacct table
  ├── [scrape + track tokens]
  │   └── Acct-Interim ──→  radacct (per page)
  ├── Acct-Stop        ──→  radacct (final totals)
  └── Submit matches   ──→  RabbitMQ ──→ missing-table
```

## Throttling Ladder

| Budget % | Action | Detail |
|----------|--------|--------|
| 0-70% | Normal | Full speed, authorized model |
| 70-90% | Downgrade | Switch to cheaper model |
| 90-100% | Reduce | Cap remaining pages to 5 |
| 100%+ | Kill | Stop session immediately |
