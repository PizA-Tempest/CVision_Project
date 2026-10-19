"""
ai_client.py — OpenAI first, Google Gemini free tier as fallback.

Order:
  1. OpenAI   (OPENAI_API_KEY)          — paid, existing behaviour
  2. Gemini   (GEMINI_API_KEY)          — free tier, OpenAI-compatible endpoint

Both use the official `openai` Python package; Gemini is reached via
Google's OpenAI-compatible base URL, so chat.completions.create() works
unchanged. The model name is chosen per provider.

Gemini free tier has a daily request quota per model. When one model is
exhausted (429), the next model in GEMINI_MODELS is tried automatically.
"""

from __future__ import annotations

import os

from openai import AsyncOpenAI, OpenAI

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
# Checked in order. Each free-tier model has its own daily quota, so running
# out on one does not block the others. GEMINI_MODEL (env) overrides #1.
GEMINI_MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-3.8-flash",
    "gemini-flash-latest",
]
OPENAI_MODEL = "gpt-4o-mini"


def _gemini_models() -> list[str]:
    first = os.getenv("GEMINI_MODEL")
    models = [m for m in GEMINI_MODELS if m != first]
    return ([first] if first else []) + models


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
        return OpenAI(**_gemini_kwargs()), _gemini_models()[0]
    raise RuntimeError(
        "No AI key set. Provide OPENAI_API_KEY or GEMINI_API_KEY in .env / secrets."
    )


def get_async_client():
    """Async client. Same preference order as get_client()."""
    if os.getenv("OPENAI_API_KEY"):
        return AsyncOpenAI(**_openai_kwargs()), OPENAI_MODEL
    if os.getenv("GEMINI_API_KEY"):
        return AsyncOpenAI(**_gemini_kwargs()), _gemini_models()[0]
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


def _is_quota_error(err: Exception) -> bool:
    text = str(err).lower()
    return "429" in text or "quota" in text or "resource_exhausted" in text


def _create_once(client, model: str, messages: list, extra: dict):
    response = client.chat.completions.create(model=model, messages=messages, **extra)
    if _is_truncated(response):
        budget = int(extra.get("max_tokens") or 1000)
        extra = dict(extra)
        extra["max_tokens"] = max(budget * 4, 4096)
        response = client.chat.completions.create(model=model, messages=messages, **extra)
        if _is_truncated(response):
            raise RuntimeError(
                f"{model} returned an empty or truncated response — check the AI key / model."
            )
    return response


def chat_completion(client, model: str, messages: list, **extra):
    """
    One chat call.

    - OpenAI primary: on failure with GEMINI_API_KEY set, retries on Gemini.
    - Gemini primary: on quota (429), walks the remaining GEMINI_MODELS list.
    - Truncated/empty answers are retried once with a larger token budget.
    """
    extra = dict(extra)

    if model != OPENAI_MODEL:
        # Gemini primary — walk model list on quota errors.
        models = [model] + [m for m in _gemini_models() if m != model]
        last_err: Exception | None = None
        for i, m in enumerate(models):
            try:
                return _create_once(client, m, messages, extra)
            except Exception as err:
                last_err = err
                if i < len(models) - 1 and _is_quota_error(err):
                    continue
                raise
        raise last_err if last_err else RuntimeError("Gemini request failed.")

    # OpenAI primary.
    try:
        return _create_once(client, model, messages, extra)
    except Exception as primary_err:
        if not os.getenv("GEMINI_API_KEY"):
            raise
        # Auth / quota / transport — try Gemini free tier.
        fallback = OpenAI(**_gemini_kwargs())
        last_err: Exception | None = None
        for i, m in enumerate(_gemini_models()):
            try:
                return _create_once(fallback, m, messages, extra)
            except Exception as err:
                last_err = err
                if i < len(_gemini_models()) - 1 and _is_quota_error(err):
                    continue
                # Non-quota error on the first Gemini model: still surface it
                # with the OpenAI cause attached.
                raise RuntimeError(
                    f"OpenAI failed ({primary_err}); Gemini failed ({err})"
                ) from primary_err
        raise last_err if last_err else primary_err


async def achat_completion(client, model: str, messages: list, **extra):
    """Async twin of chat_completion — same fallback / quota walk logic."""
    extra = dict(extra)

    async def _once(c, m):
        response = await c.chat.completions.create(model=m, messages=messages, **extra)
        if _is_truncated(response):
            budget = int(extra.get("max_tokens") or 1000)
            larger = dict(extra)
            larger["max_tokens"] = max(budget * 4, 4096)
            response = await c.chat.completions.create(model=m, messages=messages, **larger)
            if _is_truncated(response):
                raise RuntimeError(
                    f"{m} returned an empty or truncated response — check the AI key / model."
                )
        return response

    if model != OPENAI_MODEL:
        models = [model] + [m for m in _gemini_models() if m != model]
        last_err: Exception | None = None
        for i, m in enumerate(models):
            try:
                return await _once(client, m)
            except Exception as err:
                last_err = err
                if i < len(models) - 1 and _is_quota_error(err):
                    continue
                raise
        raise last_err if last_err else RuntimeError("Gemini request failed.")

    try:
        return await _once(client, model)
    except Exception as primary_err:
        if not os.getenv("GEMINI_API_KEY"):
            raise
        fallback = AsyncOpenAI(**_gemini_kwargs())
        last_err: Exception | None = None
        for i, m in enumerate(_gemini_models()):
            try:
                return await _once(fallback, m)
            except Exception as err:
                last_err = err
                if i < len(_gemini_models()) - 1 and _is_quota_error(err):
                    continue
                raise RuntimeError(
                    f"OpenAI failed ({primary_err}); Gemini failed ({err})"
                ) from primary_err
        raise last_err if last_err else primary_err
