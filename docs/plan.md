# iron-claw: RADIUS-Controlled LLM Match Scraper

## Context

The existing `match-scraper` uses deterministic Playwright automation to scrape MLS Next match data and submit it to `missing-table` via RabbitMQ. We want to build a **new LLM-powered scraper** that uses an AI agent (starting with direct API calls, eventually OpenClaw) to parse match pages. Because LLM calls cost real money and autonomous agents can behave unpredictably, we need a **metering and control layer** -- exactly what RADIUS was built for.

FreeRADIUS acts as the session controller: authenticating the scraper before it runs, authorizing token budgets and model tiers, tracking consumption via accounting, and enforcing throttling/shutdown when budgets are exceeded. This mirrors how satellite ISPs use RADIUS to control subscriber terminal sessions.

## Architecture

```
iron-claw (CLI / CronJob)
  |
  +-- Access-Request --> FreeRADIUS (Docker, local)
  |     |                   |
  |     |                   +-- rlm_sql_postgresql --> Supabase PostgreSQL
  |     |                       (radcheck, radreply, radacct tables)
  |     |
  |     +-- Access-Accept:
  |           Session-Timeout=1800, MT-Token-Budget=50000,
  |           MT-Model-Allowed=claude-haiku-4-5, MT-Max-Pages=20
  |
  +-- Acct-Start --> FreeRADIUS --> radacct
  |
  +-- [scrape pages with LLM, track tokens]
  |     +-- Acct-Interim (per page) --> radacct
  |     +-- Policy engine checks budget --> throttle/downgrade/kill
  |
  +-- Acct-Stop --> radacct (final totals)
  |
  +-- Submit matches --> RabbitMQ --> missing-table Celery workers
```

## Custom RADIUS Dictionary (Vendor: MissTable, ID: 99901)

```
MT-Token-Budget         1  integer    # max tokens per session
MT-Tokens-Used          2  integer    # current consumption
MT-Token-Cost-Cents     3  integer    # estimated cost
MT-Model-Allowed        4  string     # "claude-haiku-4-5"
MT-Allowed-Domains      5  string     # "mlssoccer.com"
MT-Browser-Enabled      6  integer    # 1=yes, 0=no
MT-Shell-Enabled        7  integer    # always 0
MT-Max-Pages            8  integer    # max page navigations
MT-Max-LLM-Calls        9  integer    # max LLM invocations
MT-Output-Queue        10  string     # "match_processing"
MT-Pages-Visited       11  integer    # pages processed (acct)
MT-LLM-Calls-Made     12  integer    # LLM calls made (acct)
MT-Matches-Found      13  integer    # matches extracted (acct)
MT-Monthly-Budget      14  integer    # monthly token cap
MT-Monthly-Used        15  integer    # month-to-date tokens
```

## Throttling Ladder

| Budget % | Action | Detail |
|----------|--------|--------|
| 0-70% | Normal | Full speed, authorized model |
| 70-90% | Downgrade model | CoA: switch to cheaper model |
| 90-100% | Reduce pages | CoA: cap remaining pages to 5 |
| 100%+ | Kill session | Disconnect: stop immediately |
| Monthly cap | Reject at start | Access-Reject before run begins |

---

## Phase 1: Foundation -- Repo Setup + FreeRADIUS Docker

**Status: COMPLETE**

### Goal
New repo skeleton + FreeRADIUS Docker container with PostgreSQL SQL backend and custom dictionary.

### What was built
- Full repo structure at `~/gitrepos/iron-claw/`
- `docker/Dockerfile` extending `ghcr.io/silverbeer/freeradius-lab:latest` with `freeradius-postgresql`
- `docker/docker-compose.yml` with `network_mode: host`, config volume mounts, env vars for Supabase
- `raddb/dictionary.misstable` — Custom VSA dictionary (Vendor MissTable, ID 99901)
- `raddb/clients.conf` — localhost NAS client
- `raddb/mods-available/sql` — `rlm_sql_postgresql` -> Supabase via env vars
- `raddb/mods-config/sql/main/postgresql/queries.conf` — Standard FreeRADIUS queries
- `raddb/sites-available/default` — authorize/authenticate/accounting/post-auth with SQL
- `src/radius/dictionary` — pyrad dictionary (standard + MissTable VSAs)
- `tests/conftest.py` — pyrad fixtures (reused pattern from freeradius-lab)
- `.github/workflows/test.yml` and `docker-image.yml`
- 16 passing unit tests

### Verification (pending — requires live infra)
- `docker compose up` starts FreeRADIUS with `radiusd -C` passing
- `radtest iron-claw-scraper scraper-secret localhost 0 testing123` returns Access-Accept

---

## Phase 2: RADIUS Integration -- Supabase Schema + Python Client

**Status: COMPLETE + VERIFIED**

### Goal
Add FreeRADIUS tables to Supabase, implement sqlcounter for monthly budgets, build the Python RADIUS client wrapper.

### What was built

#### In `missing-table` repo (PR #218, merged)
- Migration: `supabase-local/migrations/20260215000000_add_radius_tables.sql`
- Creates standard FreeRADIUS tables: `radcheck`, `radreply`, `radacct`, `radusergroup`, `radgroupcheck`, `radgroupreply`, `radpostauth`
- Seeds `iron-claw-scraper` user with password + VSA reply attributes

#### In `iron-claw` repo (PR #1, merged)
- `raddb/mods-available/sqlcounter` — monthly token budget enforcement via `SUM(acctinputoctets)`
- `src/radius/client.py` — `RadiusSessionClient` with `authenticate()`, `acct_start/interim/stop()`
- `src/radius/models.py` — `RadiusConfig`, `SessionGrant`, `AccountingUpdate` (Pydantic)
- Updated `sites-available/default` with `monthly_token_counter` in authorize section
- Fixed Dockerfile COPY paths and added mods-enabled symlinks

#### Integration bug fixes (PR #3, merged)
9 bugs found and fixed during first live integration test on macOS ARM64 (Mac Mini):

| File | Bug | Fix |
|------|-----|-----|
| `docker/Dockerfile` | AL2023 `freeradius-postgresql-3.2.5` has hard dep on `freeradius=3.2.5`, conflicts with base image's 3.2.8 | `dnf download` + `rpm --nodeps` (ABI-compatible within 3.2.x) |
| `docker/Dockerfile` | Missing `libpq.so.5` at runtime | Added `postgresql-libs` to `dnf install` |
| `raddb/mods-available/sql` | `${ENV:VAR}` is not valid FreeRADIUS syntax | Changed to `$ENV{VAR}` |
| `raddb/mods-config/.../queries.conf` | `${acct_table1}` not found from nested accounting sections | Changed to `${....acct_table1}` (4 dots = 4 scope levels up to sql{}) |
| `raddb/mods-config/.../queries.conf` | `SQL-User-Name` was empty in all queries | Added `sql_user_name = "%{User-Name}"` |
| `raddb/mods-available/sqlcounter` | Missing required `key` config item | Added `key = User-Name` |
| `raddb/dictionary.misstable` | `MT-Monthly-Used` attribute conflicts with sqlcounter internal registration | Removed from dictionary (sqlcounter creates it) |
| `raddb/clients.conf` | Only `127.0.0.1`/`::1` clients — Docker bridge traffic dropped silently | Added `172.16.0.0/12` client for Docker bridge |
| `docker/docker-compose.yml` | `network_mode: host` doesn't forward UDP on Docker Desktop macOS | Switched to explicit `ports: 1812:1812/udp, 1813:1813/udp` |

### Verification (PASSED — 2026-02-15)
- `radiusd -C` config syntax check: **PASS**
- `radtest iron-claw-scraper scraper-secret localhost 0 testing123`: **Access-Accept** with all 10 VSA reply attributes
- 12/12 integration tests pass (8 auth + 4 accounting) in 3.12s
- `radacct` table confirms token counts in `acctinputoctets` and match counts in `acctoutputoctets`
- `radpostauth` table confirms post-auth logging
- Monthly budget enforcement not yet tested (requires exceeding budget)

### Integration test sequence (updated for macOS)
```bash
# 1. Ensure Supabase local is running (applies RADIUS tables migration)
#    If tables don't exist yet, apply migration directly:
PGPASSWORD=postgres psql -h localhost -p 54332 -U postgres -d postgres \
  -f ~/gitrepos/missing-table/supabase-local/migrations/20260215000000_add_radius_tables.sql

# 2. Build & start FreeRADIUS pointed at Supabase local
cd ~/gitrepos/iron-claw/docker
DOCKER_DEFAULT_PLATFORM=linux/amd64 \
  RADIUS_SQL_SERVER=host.docker.internal \
  RADIUS_SQL_PORT=54332 \
  docker compose up -d --build

# 3. Verify config syntax
docker exec iron-claw-radius radiusd -C

# 4. Test auth (from inside container — Docker Desktop Mac UDP limitation)
docker exec iron-claw-radius radtest iron-claw-scraper scraper-secret localhost 0 testing123

# 5. Run integration tests (from Docker container on same network)
docker run --rm --platform linux/amd64 --network docker_default \
  -v ~/gitrepos/iron-claw:/app -w /app \
  python:3.14-slim \
  sh -c "pip install pyrad pytest -q && RADIUS_SERVER=iron-claw-radius \
    pytest tests/test_auth.py tests/test_accounting.py -m integration -v"
```

### Lessons learned
- **FreeRADIUS `$INCLUDE` scope**: `${var}` references in included files use relative scoping — nested sections need `${....var}` (dots = levels up) to reach parent module variables.
- **Docker Desktop macOS + UDP**: `network_mode: host` does not reliably forward UDP ports from Mac host to container. Use explicit port mapping + run tests from a container on the same Docker network.
- **RPM version pinning**: Custom-built RPMs (3.2.8) conflict with distro subpackages (3.2.5). The `rlm_sql_postgresql.so` module is ABI-compatible within 3.2.x, so `--nodeps` is a valid workaround.
- **sqlcounter counter_name**: The attribute specified in `counter_name` must NOT be defined in the dictionary — the sqlcounter module registers it internally as `integer64`.

---

## Phase 3: LLM Scraper -- Core Engine with Token Tracking

**Status: CODE COMPLETE, NOT INTEGRATION TESTED**

### Goal
Build the LLM-powered scraper with an LLM-agnostic interface, token tracking, and full RADIUS session lifecycle.

### What was built
- `src/llm/protocol.py` — `LLMProvider` protocol: `extract_matches(html) -> (list[MatchData], TokenUsage)`
- `src/llm/anthropic_provider.py` — Claude API implementation with structured output prompt
- `src/llm/mock_provider.py` — Configurable mock for testing (adjustable token burn rate)
- `src/scraper/engine.py` — `ScrapingEngine` orchestrator (auth -> scrape -> acct lifecycle)
- `src/scraper/page_fetcher.py` — httpx page fetcher
- `src/models/session.py` — `ScrapingSession` state tracker with budget tracking
- `src/models/match_data.py` — `MatchData` contract model

### Verification (pending)
- `iron-claw scrape --dry-run` with MockProvider: auth -> scrape -> acct-stop
- Full run with Claude API: extracts real matches from MLS Next HTML
- `radacct` table shows token counts in `acctinputoctets`

---

## Phase 4: Policy Engine -- Throttling Ladder

**Status: CODE COMPLETE, UNIT TESTED**

### Goal
Client-side budget enforcement with graduated throttling.

### What was built
- `src/policy/rules.py` — `ThrottleAction`, `ThrottleRule`, `DEFAULT_THROTTLE_LADDER`
- `src/policy/engine.py` — `PolicyEngine`: evaluates `session.budget_percentage()` against ladder
- Integration in `ScrapingEngine`: after each page, evaluates policy and acts on result

### Verification
- **Unit tests passing**: policy engine returns correct actions at each budget threshold (5 tests)
- **Pending**: integration test with MockProvider that burns tokens fast, verify model downgrade at 70%, kill at 100%

---

## Phase 5: End-to-End Integration

**Status: CODE COMPLETE, NOT TESTED**

### Goal
Wire iron-claw output to missing-table via RabbitMQ. Deploy as K3s CronJob.

### What was built
- `src/queue/client.py` — `MatchQueueClient` (RabbitMQ/pika)
- `src/cli/main.py` — Typer CLI: `auth-test`, `scrape`, `status` commands
- `k3s/iron-claw/cronjob.yaml` — K3s CronJob (daily at 6 AM UTC)
- `k3s/iron-claw/configmap.yaml` — non-secret config
- `k3s/iron-claw/secret.yaml` — template for RADIUS creds, RabbitMQ URL, API key

### Verification (pending)
End-to-end test:
1. Supabase local running (with RADIUS tables)
2. FreeRADIUS Docker running
3. RabbitMQ running (K3s or local)
4. missing-table Celery worker running
5. `iron-claw scrape` -> auth -> scrape -> submit -> matches appear in missing-table DB
6. `radacct` shows complete session with token totals

---

## Phase 6: Observability -- Grafana Dashboards

**Status: NOT STARTED**

### Goal
Grafana dashboards for token usage, session metrics, cost tracking.

### Planned files
- `src/utils/metrics.py` — IronClawMetrics (OpenTelemetry counters/histograms)
- `dashboards/` — Dashboard JSON models (token usage, session activity, cost tracker)
- `terraform/grafana/` — Terraform IaC for dashboards + alerts (reuse freeradius-lab pattern)

### Key Metrics
- `iron_claw_tokens_consumed_total` (counter, labels: model, session_id)
- `iron_claw_sessions_total` (counter, labels: result=accept/reject, terminate_cause)
- `iron_claw_throttle_events_total` (counter, labels: action=downgrade/reduce/kill)
- `iron_claw_cost_cents_total` (counter)
- `iron_claw_session_duration_seconds` (histogram)

### Alerts
- Monthly budget > 90% utilized -> warning
- Session failed (Access-Reject or error termination) -> critical
- No sessions in 48 hours -> warning

---

## Cross-Repo Changes Summary

| Repo | Changes | Status |
|------|---------|--------|
| **iron-claw** (new) | All phases above | Phases 1-4 code complete, Phase 2 verified |
| **missing-table** | 1 migration adding RADIUS tables + seed data | PR #218 merged |
| **freeradius-lab** | None (Docker image used as base) | N/A |
| **match-scraper** | None (patterns duplicated per convention) | N/A |

## Key Risks

1. **Supabase connection pooling (PgBouncer)** — FreeRADIUS may need `?sslmode=require` and proper connection handling. Test early.
2. ~~**VSA encoding in pyrad** — both pyrad and FreeRADIUS dictionaries must define the vendor block consistently. Test round-trip.~~ **RESOLVED**: VSA round-trip verified — all 10 MissTable VSAs returned correctly in Access-Accept and parsed by pyrad.
3. ~~**Token-to-octets mapping** — repurposing `acctinputoctets` for token counts is pragmatic but unconventional. Document clearly.~~ **RESOLVED**: Accounting tests confirm `acctinputoctets` (tokens) and `acctoutputoctets` (matches) write correctly to `radacct`.
4. **Network: Docker <-> K3s <-> Supabase** — FreeRADIUS on host Docker, scraper in K3s, Supabase on localhost. Use `host.k3d.internal` from K3s pods.
5. **Docker Desktop macOS + UDP** — `network_mode: host` does not forward UDP. Use explicit port mapping and run RADIUS clients from containers on the same Docker network. (Discovered during Phase 2 verification.)
6. **RPM version mismatch** — Base image has custom FreeRADIUS 3.2.8 RPM; AL2023 repo subpackages are 3.2.5. Workaround: `rpm --nodeps`. Long-term fix: publish postgresql subpackage from freeradius-lab CI.
