"""FastAPI proxy server — forwards Anthropic Messages API requests."""

from __future__ import annotations

import json

import httpx
import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from proxy.config import ProxyConfig

logger = structlog.get_logger()


def create_app(config: ProxyConfig) -> FastAPI:
    """Build the FastAPI application with the given config."""
    app = FastAPI(title="iron-claw proxy", version="0.1.0")
    client = httpx.AsyncClient(base_url=config.anthropic_base_url, timeout=120.0)

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await client.aclose()

    @app.post("/v1/messages", response_model=None)
    async def messages(request: Request) -> JSONResponse | StreamingResponse:
        body = await request.json()
        model = body.get("model", "unknown")
        is_stream = body.get("stream", False)

        logger.info("proxy.request", model=model, stream=is_stream)

        headers = {
            "x-api-key": config.anthropic_api_key,
            "anthropic-version": request.headers.get("anthropic-version", "2023-06-01"),
            "content-type": "application/json",
        }

        if is_stream:
            return await _handle_streaming(client, body, headers, model)
        return await _handle_non_streaming(client, body, headers, model)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


async def _handle_non_streaming(
    client: httpx.AsyncClient,
    body: dict,
    headers: dict,
    model: str,
) -> JSONResponse:
    """Forward a non-streaming request and return the full response."""
    resp = await client.post("/v1/messages", json=body, headers=headers)
    data = resp.json()

    usage = data.get("usage", {})
    logger.info(
        "proxy.response",
        model=model,
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        status=resp.status_code,
    )

    return JSONResponse(content=data, status_code=resp.status_code)


async def _handle_streaming(
    client: httpx.AsyncClient,
    body: dict,
    headers: dict,
    model: str,
) -> StreamingResponse:
    """Forward a streaming request and relay SSE events."""
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

    return StreamingResponse(
        relay_events(),
        media_type="text/event-stream",
        status_code=resp.status_code,
    )
