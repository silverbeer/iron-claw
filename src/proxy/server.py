"""FastAPI proxy server — forwards LLM API requests (Anthropic + OpenAI)."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

import httpx
import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from policy.engine import PolicyEngine
from policy.rules import ThrottleAction
from proxy.config import ProxyConfig
from proxy.provider import DOWNGRADE_MODELS
from proxy.session import ProxySession
from radius.client import RadiusSessionClient
from radius.models import RadiusConfig

logger = structlog.get_logger()


def _enforce_policy(
    policy: PolicyEngine,
    session: ProxySession | None,
    config: ProxyConfig,
    body: dict,
    model: str,
    provider: str,
) -> JSONResponse | str:
    """Evaluate policy and apply throttle actions.

    Returns a JSONResponse (429) if the session should be killed,
    or the (possibly downgraded) model name to use for the request.
    """
    if not session or config.policy_mode == "off":
        return model

    action = policy.evaluate(session)

    if config.policy_mode == "monitor":
        if action != ThrottleAction.NONE:
            logger.info(
                "policy.monitor",
                action=action.value,
                model=model,
                budget_pct=round(session.budget_percentage, 1),
            )
        return model

    # enforce mode
    if action == ThrottleAction.KILL_SESSION:
        logger.warning("proxy.rejected", model=model, budget_pct=session.budget_percentage)
        return JSONResponse(
            status_code=429,
            content={
                "type": "error",
                "error": {
                    "type": "rate_limit_error",
                    "message": (
                        f"Token budget exceeded ({session.tokens_used}"
                        f"/{session.grant.token_budget}). "
                        "Session killed by policy engine."
                    ),
                },
            },
        )
    if action == ThrottleAction.DOWNGRADE_MODEL:
        downgrade_target = DOWNGRADE_MODELS[provider]
        original = body.get("model")
        body["model"] = downgrade_target
        model = downgrade_target
        logger.info("proxy.downgrade", original=original, downgraded_to=downgrade_target)
    if action == ThrottleAction.REDUCE_PAGES:
        logger.info(
            "proxy.warning",
            detail="Budget 90-100%, approaching limit",
            budget_pct=round(session.budget_percentage, 1),
        )

    return model


def create_app(
    config: ProxyConfig,
    *,
    radius_config: RadiusConfig | None = None,
    username: str | None = None,
    password: str | None = None,
) -> FastAPI:
    """Build the FastAPI application with the given config."""
    session: ProxySession | None = None
    radius_client: RadiusSessionClient | None = None
    policy = PolicyEngine()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal session, radius_client

        logger.info("proxy.started", policy_mode=config.policy_mode)

        if radius_config and username and password:
            radius_client = RadiusSessionClient(radius_config)
            session = _radius_start(radius_client, username, password)
            logger.info(
                "proxy.radius.ready",
                token_budget=session.grant.token_budget,
                model_allowed=session.grant.model_allowed,
                policy_mode=config.policy_mode,
            )

        yield

        if session and radius_client:
            _radius_stop(radius_client, session)

    app = FastAPI(title="iron-claw proxy", version="0.1.0", lifespan=lifespan)
    anthropic_client = httpx.AsyncClient(base_url=config.anthropic_base_url, timeout=120.0)
    openai_client = httpx.AsyncClient(base_url=config.openai_base_url, timeout=120.0)

    # ------------------------------------------------------------------
    # Anthropic: POST /v1/messages
    # ------------------------------------------------------------------
    @app.post("/v1/messages", response_model=None)
    async def messages(request: Request) -> JSONResponse | StreamingResponse:
        body = await request.json()
        model = body.get("model", "unknown")
        is_stream = body.get("stream", False)

        result = _enforce_policy(policy, session, config, body, model, "anthropic")
        if isinstance(result, JSONResponse):
            return result
        model = result

        logger.info("proxy.request", model=model, stream=is_stream, provider="anthropic")

        headers = {
            "x-api-key": config.anthropic_api_key,
            "anthropic-version": request.headers.get("anthropic-version", "2023-06-01"),
            "content-type": "application/json",
        }

        if is_stream:
            return await _handle_anthropic_streaming(
                anthropic_client, body, headers, model, session, radius_client
            )
        return await _handle_anthropic_non_streaming(
            anthropic_client, body, headers, model, session, radius_client
        )

    # ------------------------------------------------------------------
    # OpenAI: POST /v1/chat/completions
    # ------------------------------------------------------------------
    @app.post("/v1/chat/completions", response_model=None)
    async def chat_completions(request: Request) -> JSONResponse | StreamingResponse:
        body = await request.json()
        model = body.get("model", "unknown")
        is_stream = body.get("stream", False)

        result = _enforce_policy(policy, session, config, body, model, "openai")
        if isinstance(result, JSONResponse):
            return result
        model = result

        logger.info("proxy.request", model=model, stream=is_stream, provider="openai")

        headers = {
            "Authorization": f"Bearer {config.openai_api_key}",
            "content-type": "application/json",
        }

        # Ask OpenAI to include usage in streaming responses
        if is_stream:
            body.setdefault("stream_options", {})["include_usage"] = True
            return await _handle_openai_streaming(
                openai_client, body, headers, model, session, radius_client
            )
        return await _handle_openai_non_streaming(
            openai_client, body, headers, model, session, radius_client
        )

    # ------------------------------------------------------------------
    # Health / Status
    # ------------------------------------------------------------------
    @app.get("/health")
    async def health() -> dict:
        info: dict = {"status": "ok"}
        if session:
            info["radius"] = True
            info["tokens_used"] = session.tokens_used
            info["tokens_remaining"] = session.tokens_remaining
            info["budget_pct"] = round(session.budget_percentage, 1)
            info["llm_calls"] = session.llm_calls_made
        return info

    @app.get("/status")
    async def status() -> dict:
        if not session:
            return {
                "status": "no_radius_session",
                "mode": "bare",
                "policy_mode": config.policy_mode,
            }
        return {
            "status": "active",
            "policy_mode": config.policy_mode,
            "session_id": session.session_id,
            "username": session.username,
            "model_allowed": session.grant.model_allowed,
            "token_budget": session.grant.token_budget,
            "tokens_used": session.tokens_used,
            "tokens_remaining": session.tokens_remaining,
            "budget_pct": round(session.budget_percentage, 1),
            "llm_calls_made": session.llm_calls_made,
            "llm_calls_remaining": session.llm_calls_remaining,
            "elapsed_seconds": session.elapsed_seconds,
        }

    return app


# ======================================================================
# RADIUS helpers
# ======================================================================


def _radius_start(
    radius_client: RadiusSessionClient,
    username: str,
    password: str,
) -> ProxySession:
    """Authenticate via RADIUS and start accounting session."""
    grant = radius_client.authenticate(username, password)
    session_id = radius_client.generate_session_id()
    radius_client.acct_start(session_id, username)

    return ProxySession(
        session_id=session_id,
        username=username,
        grant=grant,
    )


def _radius_stop(radius_client: RadiusSessionClient, session: ProxySession) -> None:
    """Send accounting stop with final totals."""
    update = session.to_accounting_update()
    radius_client.acct_stop(session.session_id, session.username, update)
    logger.info(
        "proxy.radius.stopped",
        tokens_used=session.tokens_used,
        llm_calls=session.llm_calls_made,
        elapsed=session.elapsed_seconds,
    )


def _record_and_report(
    session: ProxySession | None,
    radius_client: RadiusSessionClient | None,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """Record usage in session and send interim accounting if RADIUS is active."""
    if not session:
        return
    session.record_usage(input_tokens, output_tokens)
    if radius_client:
        update = session.to_accounting_update()
        radius_client.acct_interim(session.session_id, session.username, update)


# ======================================================================
# Anthropic handlers
# ======================================================================


async def _handle_anthropic_non_streaming(
    client: httpx.AsyncClient,
    body: dict,
    headers: dict,
    model: str,
    session: ProxySession | None,
    radius_client: RadiusSessionClient | None,
) -> JSONResponse:
    """Forward a non-streaming Anthropic request and return the full response."""
    resp = await client.post("/v1/messages", json=body, headers=headers)
    data = resp.json()

    usage = data.get("usage", {})
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)

    logger.info(
        "proxy.response",
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        status=resp.status_code,
    )

    _record_and_report(session, radius_client, input_tokens, output_tokens)

    return JSONResponse(content=data, status_code=resp.status_code)


async def _handle_anthropic_streaming(
    client: httpx.AsyncClient,
    body: dict,
    headers: dict,
    model: str,
    session: ProxySession | None,
    radius_client: RadiusSessionClient | None,
) -> StreamingResponse:
    """Forward a streaming Anthropic request and relay SSE events."""
    req = client.build_request("POST", "/v1/messages", json=body, headers=headers)
    resp = await client.send(req, stream=True)

    input_tokens = 0
    output_tokens = 0

    async def relay_events():
        nonlocal input_tokens, output_tokens

        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                try:
                    event = json.loads(line[6:])
                    usage = event.get("usage", {})
                    if "input_tokens" in usage:
                        input_tokens = usage["input_tokens"]
                    if "output_tokens" in usage:
                        output_tokens = usage["output_tokens"]
                except json.JSONDecodeError:
                    pass
            yield f"{line}\n"

        await resp.aclose()

        logger.info(
            "proxy.response",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stream=True,
        )

        _record_and_report(session, radius_client, input_tokens, output_tokens)

    return StreamingResponse(
        relay_events(),
        media_type="text/event-stream",
        status_code=resp.status_code,
    )


# ======================================================================
# OpenAI handlers
# ======================================================================


async def _handle_openai_non_streaming(
    client: httpx.AsyncClient,
    body: dict,
    headers: dict,
    model: str,
    session: ProxySession | None,
    radius_client: RadiusSessionClient | None,
) -> JSONResponse:
    """Forward a non-streaming OpenAI request and return the full response."""
    resp = await client.post("/v1/chat/completions", json=body, headers=headers)
    data = resp.json()

    usage = data.get("usage", {})
    input_tokens = usage.get("prompt_tokens", 0)
    output_tokens = usage.get("completion_tokens", 0)

    logger.info(
        "proxy.response",
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        status=resp.status_code,
    )

    _record_and_report(session, radius_client, input_tokens, output_tokens)

    return JSONResponse(content=data, status_code=resp.status_code)


async def _handle_openai_streaming(
    client: httpx.AsyncClient,
    body: dict,
    headers: dict,
    model: str,
    session: ProxySession | None,
    radius_client: RadiusSessionClient | None,
) -> StreamingResponse:
    """Forward a streaming OpenAI request and relay SSE events."""
    req = client.build_request("POST", "/v1/chat/completions", json=body, headers=headers)
    resp = await client.send(req, stream=True)

    input_tokens = 0
    output_tokens = 0

    async def relay_events():
        nonlocal input_tokens, output_tokens

        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                payload = line[6:].strip()
                if payload == "[DONE]":
                    yield f"{line}\n"
                    continue
                try:
                    event = json.loads(payload)
                    usage = event.get("usage") or {}
                    if "prompt_tokens" in usage:
                        input_tokens = usage["prompt_tokens"]
                    if "completion_tokens" in usage:
                        output_tokens = usage["completion_tokens"]
                except json.JSONDecodeError:
                    pass
            yield f"{line}\n"

        await resp.aclose()

        logger.info(
            "proxy.response",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stream=True,
        )

        _record_and_report(session, radius_client, input_tokens, output_tokens)

    return StreamingResponse(
        relay_events(),
        media_type="text/event-stream",
        status_code=resp.status_code,
    )
