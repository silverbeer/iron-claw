"""Proxy configuration via environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class ProxyConfig(BaseSettings):
    """Settings for the LLM proxy server."""

    model_config = {"env_prefix": "PROXY_"}

    port: int = 8100
    host: str = "127.0.0.1"
    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com"
    policy_mode: str = "enforce"
