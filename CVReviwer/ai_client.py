"""
ai_client.py — OpenAI first, Google Gemini free tier as fallback.

Order:
  1. OpenAI   (OPENAI_API_KEY)          — paid, existing behaviour
  2. Gemini   (GEMINI_API_KEY)          — free tier, OpenAI-compatible endpoint

Both use the official `openai` Python package; Gemini is reached via
Google's OpenAI-compatible base URL, so chat.completions.create() works
unchanged. The model name is chosen per provider.
"""

from __future__ import annotations

import os

from openai import AsyncOpenAI, OpenAI

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
GEMINI_MODEL = "gemini-3.8-flash"
OPENAI_MODEL = "gpt-4o-mini"


def active_provider() -> str:
    """Which provider will be used first: 'openai', 'gemini', or 'none'."""
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    if os.getenv("GEMINI_API_KEY"):
        return "gemini"
    return "none"


def _gemini_kwargs() -> dict:
    return {
        "api_key": os.getenv("GEMINI_API_KEY"),
        "base_url": GEMINI_BASE_URL,
    }


def _openai_kwargs() -> dict:
    return {"api_key": os.getenv("OPENAI_API_KEY")}


def get_client():
    """Sync client. Prefers OpenAI; uses Gemini when only GEMINI_API_KEY is set."""
    if os.getenv("OPENAI_API_KEY"):
        return OpenAI(**_openai_kwargs()), OPENAI_MODEL
    if os.getenv("GEMINI_API_KEY"):
        return OpenAI(**_gemini_kwargs()), GEMINI_MODEL
    raise RuntimeError(
        "No AI key set. Provide OPENAI_API_KEY or GEMINI_API_KEY in .env / secrets."
    )


def get_async_client():
    """Async client. Same preference order as get_client()."""
    if os.getenv("OPENAI_API_KEY"):
        return AsyncOpenAI(**_openai_kwargs()), OPENAI_MODEL
    if os.getenv("GEMINI_API_KEY"):
        return AsyncOpenAI(**_gemini_kwargs()), GEMINI_MODEL
    raise RuntimeError(
        "No AI key set. Provide OPENAI_API_KEY or GEMINI_API_KEY in .env / secrets."
    )


def _is_truncated(response) -> bool:
    """True when the model ran out of tokens before finishing the answer."""
    if not response.choices:
        return True
    choice = response.choices[0]
    if choice.finish_reason in ("length", "max_tokens"):
        return True
    content = (choice.message.content or "").strip() if choice.message else ""
    if not content:
        return True
    # Heuristic: a JSON answer cut mid-object (unbalanced braces).
    if content.count("{") != content.count("}") or content.count("[") != content.count("]"):
        return True
    return False


def chat_completion(client, model: str, messages: list, **extra):
    """
    One chat call. If the primary is OpenAI and it fails with auth/rate-limit
    and a GEMINI_API_KEY is present, retries once on Gemini (free).

    Retries once with a larger token budget when the answer comes back
    truncated or empty (Gemini can also return content=None when reasoning
    consumes the whole budget).
    """
    try:
        extra = dict(extra)
        budget = int(extra.get("max_tokens") or 1000)
        response = client.chat.completions.create(
            model=model, messages=messages, **extra
        )
        if not _is_truncated(response):
            return response
        # Truncated / empty — retry once with a larger budget.
        extra["max_tokens"] = max(budget * 4, 4096)
        response = client.chat.completions.create(
            model=model, messages=messages, **extra
        )
        if _is_truncated(response):
            raise RuntimeError(
                f"{model} returned an empty or truncated response — check the AI key / model."
            )
        return response
    except Exception as primary_err:
        # Only fall back when OpenAI was the primary and Gemini is configured
        if model != OPENAI_MODEL or not os.getenv("GEMINI_API_KEY"):
            raise
        fallback = OpenAI(**_gemini_kwargs())
        extra = dict(extra)
        budget = int(extra.get("max_tokens") or 1000)
        response = fallback.chat.completions.create(
            model=GEMINI_MODEL, messages=messages, **extra
        )
        if _is_truncated(response):
            extra["max_tokens"] = max(budget * 4, 4096)
            response = fallback.chat.completions.create(
                model=GEMINI_MODEL, messages=messages, **extra
            )
        if _is_truncated(response):
            raise RuntimeError(
                f"{GEMINI_MODEL} returned an empty or truncated response — check GEMINI_API_KEY."
            ) from primary_err
        return response
