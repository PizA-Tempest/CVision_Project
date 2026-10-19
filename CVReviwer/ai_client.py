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


def chat_completion(client, model: str, messages: list, **extra):
    """
    One chat call. If the primary is OpenAI and it fails with auth/rate-limit
    and a GEMINI_API_KEY is present, retries once on Gemini (free).
    """
    try:
        return client.chat.completions.create(
            model=model, messages=messages, **extra
        )
    except Exception as primary_err:
        # Only fall back when OpenAI was the primary and Gemini is configured
        if model != OPENAI_MODEL or not os.getenv("GEMINI_API_KEY"):
            raise
        fallback = OpenAI(**_gemini_kwargs())
        return fallback.chat.completions.create(
            model=GEMINI_MODEL, messages=messages, **extra
        )
