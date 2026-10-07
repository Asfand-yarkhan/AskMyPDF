"""Chat model factory for the configured provider (Groq / OpenAI / Gemini)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from langchain_core.language_models import BaseChatModel

from app.config import get_settings


class LLMConfigError(RuntimeError):
    """The selected provider is missing an API key or package."""


def llm_configured() -> bool:
    s = get_settings()
    if s.llm_provider == "groq":
        return s.groq_api_key is not None
    if s.llm_provider == "openai":
        return s.openai_api_key is not None or s.openai_base_url is not None
    return s.google_api_key is not None


def is_rate_limit_error(exc: BaseException) -> bool:
    """Provider-agnostic check (groq/openai raise RateLimitError, Gemini ResourceExhausted)."""
    return type(exc).__name__ in {"RateLimitError", "ResourceExhausted", "TooManyRequests"}


@lru_cache(maxsize=16)
def get_chat_model(
    temperature: float = 0.0,
    purpose: Literal["main", "router"] = "main",
    effort: Literal["low", "medium", "high"] | None = None,
) -> BaseChatModel:
    """`effort` overrides the reasoning effort of reasoning models (ignored by others).

    Reasoning tokens count against per-minute token quotas, so bulk jobs (summaries)
    use "low" while single answers use the configured REASONING_EFFORT.
    """
    s = get_settings()
    model = s.resolved_router_model if purpose == "router" else s.resolved_llm_model
    if not llm_configured():
        raise LLMConfigError(
            f"LLM provider '{s.llm_provider}' has no API key. Set it in backend/.env (see .env.example)."
        )

    if s.llm_provider == "groq":
        from langchain_groq import ChatGroq

        extra: dict[str, str] = {}
        if "gpt-oss" in model:
            # Reasoning models: think harder for answers, stay fast for routing/rewrites.
            extra["reasoning_effort"] = effort or (s.reasoning_effort if purpose == "main" else "low")
        return ChatGroq(
            model=model,
            temperature=temperature,
            api_key=s.groq_api_key.get_secret_value(),  # type: ignore[union-attr]
            timeout=s.llm_timeout_s,
            # The SDK waits for the server's retry-after on 429s, so this rides out
            # per-minute token limits (e.g. Groq free tier) instead of failing.
            max_retries=s.llm_max_retries,
            **extra,
        )
    if s.llm_provider == "openai":
        from langchain_openai import ChatOpenAI

        key = s.openai_api_key.get_secret_value() if s.openai_api_key else "not-needed"
        return ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=key,
            base_url=s.openai_base_url,
            timeout=s.llm_timeout_s,
            max_retries=s.llm_max_retries,
        )
    if s.llm_provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model,
            temperature=temperature,
            google_api_key=s.google_api_key.get_secret_value(),  # type: ignore[union-attr]
            timeout=s.llm_timeout_s,
            max_retries=s.llm_max_retries,
        )
    raise LLMConfigError(f"Unknown LLM provider: {s.llm_provider}")
