# RADIUS LLM Proxy — Implementation Plan

**Feature:** Make iron-claw a general RADIUS proxy that meters all LLM API calls
**Target demo:** Feb 23, 2026
**Created:** 2026-02-17

## Target Architecture

```
WhatsApp → OpenClaw → iron-claw proxy (RADIUS auth + metering) → Anthropic API
                              ↓
                        radacct (Supabase) → Grafana dashboards
```

---

## Phase 1: Bare Proxy (pipe works, no RADIUS)

**Status: CODE COMPLETE** (smoke tested: /health OK, pending live Anthropic test)

### Goal
Requests flow through iron-claw to Anthropic. Prove the pipe works.

### New Files
- [x] `src/proxy/__init__.py` — package init
- [x] `src/proxy/config.py` — `ProxyConfig` (Pydantic settings: port, anthropic_base_url, anthropic_api_key)
- [x] `src/proxy/server.py` — FastAPI app with `POST /v1/messages` (non-streaming + streaming)

### Modified Files
- [x] `pyproject.toml` — Add deps: `fastapi`, `uvicorn[standard]`, `httpx`; add `src/proxy` to wheel packages
- [x] `src/cli/main.py` — Add `proxy` command: `iron-claw proxy --port 8100`

### How It Works
1. `iron-claw proxy --port 8100` starts FastAPI on localhost:8100
2. Client sends `POST /v1/messages` with Anthropic-format body
3. Proxy reads `ANTHROPIC_API_KEY` from env, forwards to `https://api.anthropic.com/v1/messages`
4. Non-streaming: reads full response, returns it
5. Streaming (`"stream": true`): relays SSE events via `StreamingResponse`
6. Logs request model, token counts from response `usage` field

### Context for Implementation
- Existing CLI uses Typer — add `proxy` as a new `@app.command()`
- `pyproject.toml` packages list is in `[tool.hatch.build.targets.wheel]`
- Project script entry: `iron-claw = "cli.main:app"`
- Use `structlog` (via `utils.logger`) for all logging
- `from __future__ import annotations` in all files (project convention)

### Verification
```bash
# Start proxy
cd ~/gitrepos/iron-claw && uv run iron-claw proxy --port 8100

# Test non-streaming
curl http://localhost:8100/v1/messages \
  -H "content-type: application/json" \
  -H "x-api-key: test" \
  -H "anthropic-version: 2023-06-01" \
  -d '{"model":"claude-haiku-4-5-20251001","max_tokens":50,"messages":[{"role":"user","content":"Say hi"}]}'

# Test streaming
curl http://localhost:8100/v1/messages \
  -H "content-type: application/json" \
  -H "x-api-key: test" \
  -H "anthropic-version: 2023-06-01" \
  -d '{"model":"claude-haiku-4-5-20251001","max_tokens":50,"stream":true,"messages":[{"role":"user","content":"Say hi"}]}'
```

---

## Phase 2: RADIUS Session Lifecycle

**Status: CODE COMPLETE** (pending live RADIUS test)
**Depends on:** Phase 1

### Goal
Proxy authenticates via RADIUS on startup, tracks tokens per request.

### New Files
- [x] `src/proxy/session.py` — `ProxySession` (tracks tokens_used, llm_calls_made per API call)

### Modified Files
- [x] `src/proxy/server.py` — Add RADIUS lifecycle:
  - On startup: `RadiusSessionClient.authenticate()` → `SessionGrant`
  - On startup: `acct_start()`
  - Per request: count tokens from response `usage`, `acct_interim()`
  - On shutdown: `acct_stop()` with final totals
- [x] `src/cli/main.py` — Add RADIUS options to `proxy` command (username, password, server, secret)

### Context for Implementation
- Reuse `src/radius/client.py` — `RadiusSessionClient` (authenticate, acct_start/interim/stop)
- Reuse `src/radius/models.py` — `RadiusConfig`, `SessionGrant`, `AccountingUpdate`
- RADIUS username for proxy: `iron-claw-proxy` (separate from scraper's `iron-claw-scraper`)
- `SessionGrant` returns: token_budget, model_allowed, max_llm_calls, monthly_budget, monthly_used
- `AccountingUpdate` fields: tokens_used, pages_visited, llm_calls_made, tool_calls_made, matches_found, session_time
- One RADIUS session per proxy lifecycle (start → running → stop)
- `_resolve_password()` helper already exists in `src/cli/main.py` — reuse for proxy password

### New RADIUS User (manual Supabase SQL)
```sql
INSERT INTO radcheck (username, attribute, op, value)
VALUES ('iron-claw-proxy', 'Cleartext-Password', ':=', 'proxy-secret');

INSERT INTO radreply (username, attribute, op, value) VALUES
('iron-claw-proxy', 'Session-Timeout', ':=', '86400'),
('iron-claw-proxy', 'MT-Token-Budget', ':=', '500000'),
('iron-claw-proxy', 'MT-Model-Allowed', ':=', 'claude-haiku-4-5-20251001'),
('iron-claw-proxy', 'MT-Max-LLM-Calls', ':=', '1000'),
('iron-claw-proxy', 'MT-Monthly-Budget', ':=', '2000000');
```

### Verification
```bash
# Start FreeRADIUS
cd ~/gitrepos/iron-claw/docker && docker compose up -d

# Start proxy with RADIUS
uv run iron-claw proxy --port 8100 --username iron-claw-proxy --password proxy-secret

# Should see: "Access-Accept received" + "RADIUS acct.start" in logs
# Send a request, check logs show token counts + acct.interim
# Ctrl+C, check logs show acct.stop with final totals
# Check radacct table in Supabase for session record
```

---

## Phase 3: Throttle Ladder Enforcement

**Status: NOT STARTED**
**Depends on:** Phase 2

### Goal
Budget enforcement with model downgrade at 70%, reject at 100%.

### Modified Files
- [ ] `src/proxy/server.py` — Before forwarding each request:
  1. `PolicyEngine.evaluate(session)` checks budget %
  2. `KILL_SESSION` → return HTTP 429 with budget exceeded message
  3. `DOWNGRADE_MODEL` → rewrite request body `model` field to cheaper model
  4. `REDUCE_PAGES` → adapted to reduce remaining LLM calls
  5. `NONE` → forward as-is
- [ ] `src/proxy/server.py` — Add `GET /status` endpoint showing session state, budget %, tokens remaining

### Context for Implementation
- Reuse `src/policy/engine.py` — `PolicyEngine.evaluate()` takes a session with `budget_percentage` property
- Reuse `src/policy/rules.py` — `ThrottleAction` enum: NONE, DOWNGRADE_MODEL, REDUCE_PAGES, KILL_SESSION
- `DEFAULT_THROTTLE_LADDER`: 0-70% NONE, 70-90% DOWNGRADE, 90-100% REDUCE, 100%+ KILL
- `ProxySession` (from Phase 2) needs a `budget_percentage` property to work with PolicyEngine
- For DOWNGRADE_MODEL: rewrite `model` in request JSON before forwarding
- For KILL_SESSION: return `{"type":"error","error":{"type":"rate_limit_error","message":"..."}}`

### Verification
```bash
# Set a low token budget in radreply (e.g., 1000 tokens)
# Send requests until budget hits 70% → check logs for model downgrade
# Send more until 100% → verify 429 response
# GET /status shows budget state
```

---

## Phase 4: Wire OpenClaw Through the Proxy

**Status: NOT STARTED**
**Depends on:** Phase 3

### Goal
OpenClaw's LLM calls route through iron-claw proxy.

### Modified Files
- [ ] `~/.openclaw/.env` — Add: `ANTHROPIC_BASE_URL=http://localhost:8100`
- [ ] If OpenClaw doesn't honor `ANTHROPIC_BASE_URL`, investigate its provider config

### Context for Implementation
- OpenClaw config lives at `~/.openclaw/`
- The Anthropic SDK supports `ANTHROPIC_BASE_URL` env var natively
- No code changes needed in iron-claw for this phase — just config

### Verification
```bash
# Start iron-claw proxy
# Start OpenClaw
# Send a WhatsApp message
# Check iron-claw proxy logs show the request flowing through
# Check radacct table shows token accounting
# GET http://localhost:8100/status shows accumulated usage
```

---

## Phase 5: Grafana Dashboard (Stretch Goal)

**Status: NOT STARTED**
**Depends on:** Phase 2 (only needs radacct data)

### Goal
Visual token usage dashboard for the demo.

### Approach
- Query radacct table from Grafana Cloud (Supabase PostgreSQL as data source)
- Dashboard panels: tokens over time, cost estimate, session history, budget gauge
- Use existing `terraform/grafana/` pattern from iron-claw repo

### Context for Implementation
- `terraform/grafana/` directory already exists in repo
- Supabase PostgreSQL is the data source (radacct table has token data in acctinputoctets)
- This phase is optional for Feb 23 but makes the demo more impressive

---

## Files Summary

| File | Phase | Change Type |
|------|-------|-------------|
| `src/proxy/__init__.py` | 1 | New |
| `src/proxy/config.py` | 1 | New |
| `src/proxy/server.py` | 1, 2, 3 | New, then modified |
| `src/proxy/session.py` | 2 | New |
| `src/cli/main.py` | 1, 2 | Modified |
| `pyproject.toml` | 1 | Modified |
| `~/.openclaw/.env` | 4 | Modified |

## Existing Code Reused (do not modify)

| File | What | Used In |
|------|------|---------|
| `src/radius/client.py` | RadiusSessionClient — auth + acct lifecycle | Phase 2 |
| `src/radius/models.py` | RadiusConfig, SessionGrant, AccountingUpdate | Phase 2 |
| `src/policy/engine.py` | PolicyEngine.evaluate() | Phase 3 |
| `src/policy/rules.py` | ThrottleAction, DEFAULT_THROTTLE_LADDER | Phase 3 |
| `src/utils/logger.py` | structlog configuration | All phases |
