"""Tests for OpenAI provider routing and /v1/chat/completions endpoint."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from policy.engine import PolicyEngine
from proxy.config import ProxyConfig
from proxy.provider import DOWNGRADE_MODELS, resolve_provider
from proxy.server import _enforce_policy, create_app
from proxy.session import ProxySession
from radius.models import SessionGrant

# ======================================================================
# resolve_provider
# ======================================================================


class TestResolveProvider:
    def test_gpt_models(self):
        assert resolve_provider("gpt-4o") == "openai"
        assert resolve_provider("gpt-4o-mini") == "openai"
        assert resolve_provider("gpt-3.5-turbo") == "openai"

    def test_o_series_models(self):
        assert resolve_provider("o1-preview") == "openai"
        assert resolve_provider("o3-mini") == "openai"
        assert resolve_provider("o4-mini") == "openai"

    def test_claude_models(self):
        assert resolve_provider("claude-sonnet-4-5-20250514") == "anthropic"
        assert resolve_provider("claude-haiku-4-5-20251001") == "anthropic"

    def test_unknown_defaults_to_anthropic(self):
        assert resolve_provider("some-unknown-model") == "anthropic"


# ======================================================================
# DOWNGRADE_MODELS
# ======================================================================


class TestDowngradeModels:
    def test_anthropic_downgrade(self):
        assert DOWNGRADE_MODELS["anthropic"] == "claude-haiku-4-5-20251001"

    def test_openai_downgrade(self):
        assert DOWNGRADE_MODELS["openai"] == "gpt-4o-mini"


# ======================================================================
# Fixtures
# ======================================================================


def _make_config(**kwargs) -> ProxyConfig:
    return ProxyConfig(
        anthropic_api_key="sk-ant-test",
        openai_api_key="sk-openai-test",
        policy_mode=kwargs.pop("policy_mode", "enforce"),
        **kwargs,
    )


def _make_session(token_budget: int = 100000, tokens_used: int = 0) -> ProxySession:
    grant = SessionGrant(token_budget=token_budget, max_llm_calls=1000)
    session = ProxySession(session_id="test-sess", username="test-user", grant=grant)
    session.tokens_used = tokens_used
    return session


def _openai_response(prompt_tokens: int = 10, completion_tokens: int = 20) -> dict:
    return {
        "id": "chatcmpl-abc123",
        "object": "chat.completion",
        "model": "gpt-4o",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Hello!"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def _openai_stream_events(prompt_tokens: int = 10, completion_tokens: int = 20) -> str:
    """Build raw SSE text for an OpenAI streaming response."""
    chunk_base = "chat.completion.chunk"
    delta_role = (
        f'data: {{"id":"chatcmpl-abc","object":"{chunk_base}",'
        '"choices":[{"index":0,"delta":{"role":"assistant"},'
        '"finish_reason":null}]}'
    )
    delta_content = (
        f'data: {{"id":"chatcmpl-abc","object":"{chunk_base}",'
        '"choices":[{"index":0,"delta":{"content":"Hello"},'
        '"finish_reason":null}]}'
    )
    total = prompt_tokens + completion_tokens
    usage_chunk = (
        f'data: {{"id":"chatcmpl-abc","object":"{chunk_base}",'
        f'"choices":[],"usage":{{"prompt_tokens":{prompt_tokens},'
        f'"completion_tokens":{completion_tokens},'
        f'"total_tokens":{total}}}}}'
    )
    lines = [delta_role, delta_content, usage_chunk, "data: [DONE]"]
    return "\n".join(lines)


# ======================================================================
# /v1/chat/completions — non-streaming
# ======================================================================


class TestChatCompletionsNonStreaming:
    def test_forwards_request_and_extracts_tokens(self):
        config = _make_config(policy_mode="off")
        app = create_app(config)

        mock_resp = httpx.Response(200, json=_openai_response(15, 25))

        with patch.object(
            httpx.AsyncClient, "post", new_callable=AsyncMock, return_value=mock_resp
        ):
            client = TestClient(app)
            resp = client.post(
                "/v1/chat/completions",
                json={
                    "model": "gpt-4o",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["usage"]["prompt_tokens"] == 15
        assert data["usage"]["completion_tokens"] == 25

    def test_openai_auth_header(self):
        """Verify that the OpenAI endpoint sends Authorization: Bearer."""
        config = _make_config(policy_mode="off")
        app = create_app(config)

        captured_headers = {}

        async def capture_post(self, url, **kwargs):
            captured_headers.update(kwargs.get("headers", {}))
            return httpx.Response(200, json=_openai_response())

        with patch.object(httpx.AsyncClient, "post", capture_post):
            client = TestClient(app)
            client.post(
                "/v1/chat/completions",
                json={
                    "model": "gpt-4o",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )

        assert "Authorization" in captured_headers
        assert captured_headers["Authorization"] == "Bearer sk-openai-test"


# ======================================================================
# /v1/chat/completions — streaming
# ======================================================================


class TestChatCompletionsStreaming:
    def test_streaming_relays_events_and_extracts_usage(self):
        config = _make_config(policy_mode="off")
        app = create_app(config)

        stream_text = _openai_stream_events(12, 30)

        async def mock_send(self, req, *, stream=False):
            mock_resp = httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=httpx.AsyncByteStream(),  # placeholder
            )
            lines = stream_text.split("\n")

            async def aiter_lines():
                for line in lines:
                    yield line

            mock_resp.aiter_lines = aiter_lines
            mock_resp.aclose = AsyncMock()
            return mock_resp

        with (
            patch.object(httpx.AsyncClient, "send", mock_send),
            patch.object(
                httpx.AsyncClient,
                "build_request",
                return_value=MagicMock(),
            ),
        ):
            client = TestClient(app)
            resp = client.post(
                "/v1/chat/completions",
                json={
                    "model": "gpt-4o",
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": True,
                },
            )

        assert resp.status_code == 200
        body = resp.text
        assert "Hello" in body
        assert "[DONE]" in body


# ======================================================================
# Policy enforcement on OpenAI endpoint
# ======================================================================


class TestOpenAIPolicyEnforcement:
    def test_kill_session_returns_429(self):
        """When budget is exceeded, /v1/chat/completions returns 429."""
        config = _make_config(policy_mode="enforce")
        session = _make_session(token_budget=1000, tokens_used=1500)
        policy = PolicyEngine()
        body = {"model": "gpt-4o", "messages": []}
        result = _enforce_policy(policy, session, config, body, "gpt-4o", "openai")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 429

    def test_downgrade_uses_openai_model(self):
        """When budget hits 70-90%, downgrade uses gpt-4o-mini."""
        config = _make_config(policy_mode="enforce")
        policy = PolicyEngine()
        session = _make_session(token_budget=1000, tokens_used=800)  # 80%

        body = {"model": "gpt-4o", "messages": []}
        result = _enforce_policy(policy, session, config, body, "gpt-4o", "openai")
        assert result == "gpt-4o-mini"
        assert body["model"] == "gpt-4o-mini"

    def test_downgrade_uses_anthropic_model(self):
        """When budget hits 70-90%, downgrade uses claude-haiku."""
        config = _make_config(policy_mode="enforce")
        policy = PolicyEngine()
        session = _make_session(token_budget=1000, tokens_used=800)  # 80%

        body = {"model": "claude-sonnet-4-5-20250514", "messages": []}
        result = _enforce_policy(
            policy,
            session,
            config,
            body,
            "claude-sonnet-4-5-20250514",
            "anthropic",
        )
        assert result == "claude-haiku-4-5-20251001"
        assert body["model"] == "claude-haiku-4-5-20251001"

    def test_monitor_mode_does_not_block(self):
        """In monitor mode, policy logs but does not block or downgrade."""
        config = _make_config(policy_mode="monitor")
        policy = PolicyEngine()
        session = _make_session(token_budget=1000, tokens_used=1500)

        body = {"model": "gpt-4o", "messages": []}
        result = _enforce_policy(policy, session, config, body, "gpt-4o", "openai")
        assert result == "gpt-4o"

    def test_off_mode_skips_policy(self):
        """With policy_mode=off, no enforcement occurs."""
        config = _make_config(policy_mode="off")
        policy = PolicyEngine()
        session = _make_session(token_budget=1000, tokens_used=1500)

        body = {"model": "gpt-4o", "messages": []}
        result = _enforce_policy(policy, session, config, body, "gpt-4o", "openai")
        assert result == "gpt-4o"
