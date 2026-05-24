"""LLM-generated executive commentary for financial-model outputs.

Two providers are wired: OpenAI (default) and Anthropic. The active provider
is picked by `LLM_PROVIDER` env var ("openai" or "anthropic"). All env vars
are read at call time so tests can monkey-patch them per case.

Used by plugins that opt in (currently biotech and chicken-farming).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session as SASession

from app.db.models import User


SYSTEM_PROMPT = """You are a senior financial analyst writing executive commentary on a financial model output for an investor audience. Write 2-3 short paragraphs that:

- Open with the headline result (good, bad, or neutral) in plain language.
- Discuss 2-3 key drivers behind the result.
- Flag 1-2 risks or sensitivities the investor should know about.

Be concise (target ~200 words). Interpret the numbers rather than restating them verbatim. Write flowing prose, not bullet lists. Avoid markdown formatting."""


_VALID_PROVIDERS = ("openai", "anthropic")

# Per-tier monthly token budget (input + output combined).
# Calibrated so a typical Enterprise user can generate ~500 commentaries/mo.
TIER_TOKEN_CAPS: dict[str, int] = {
    "free": 0,
    "pro": 50_000,
    "enterprise": 500_000,
}


class CommentaryError(RuntimeError):
    """Raised when LLM commentary generation fails."""


class QuotaExceeded(CommentaryError):
    """User has used up their monthly LLM token budget."""


def _provider() -> str:
    return os.environ.get("LLM_PROVIDER", "openai").strip().lower()


def _first_of_month_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _maybe_reset_quota(db: SASession, user: User) -> None:
    """Lazy monthly reset: if the stored reset_at is older than the first of
    this month, zero the counter and stamp it. Cheaper than a cron job."""
    boundary = _first_of_month_utc()
    if (
        user.llm_tokens_month_reset_at is None
        or user.llm_tokens_month_reset_at < boundary
    ):
        user.llm_tokens_this_month = 0
        user.llm_tokens_month_reset_at = boundary
        db.commit()


def remaining_quota(db: SASession, user_id: UUID) -> int:
    """Return how many LLM tokens the user has left this month."""
    user = db.get(User, user_id)
    if user is None:
        return 0
    _maybe_reset_quota(db, user)
    cap = TIER_TOKEN_CAPS.get(user.tier, 0)
    return max(0, cap - user.llm_tokens_this_month)


def generate_commentary(
    *,
    db: SASession,
    user_id: UUID,
    plugin_name: str,
    description: str,
    summary: dict[str, Any],
    max_tokens: int = 600,
) -> str:
    """Generate executive commentary for one plugin's results.

    Enforces the per-user monthly LLM token cap (see TIER_TOKEN_CAPS): raises
    QuotaExceeded if the user has no headroom before the call, and records
    actual usage afterward.
    """
    user = db.get(User, user_id)
    if user is None:
        raise CommentaryError("User not found.")
    _maybe_reset_quota(db, user)

    cap = TIER_TOKEN_CAPS.get(user.tier, 0)
    if cap <= 0:
        raise QuotaExceeded(
            "AI commentary is not included in your tier. Upgrade to use it."
        )
    if user.llm_tokens_this_month >= cap:
        raise QuotaExceeded(
            f"Monthly AI commentary budget exhausted "
            f"({user.llm_tokens_this_month:,}/{cap:,} tokens). "
            "Budget resets on the 1st."
        )

    user_prompt = (
        f"Model: {plugin_name}\n"
        f"Description: {description}\n\n"
        f"Key metrics and inputs:\n"
        f"{json.dumps(summary, default=str, indent=2)}\n\n"
        f"Write the commentary."
    )

    provider = _provider()
    if provider == "openai":
        text, tokens_used = _call_openai(user_prompt, max_tokens)
    elif provider == "anthropic":
        text, tokens_used = _call_anthropic(user_prompt, max_tokens)
    else:
        raise CommentaryError(
            f"Unknown LLM_PROVIDER: {provider!r}. "
            f"Expected one of: {', '.join(_VALID_PROVIDERS)}."
        )

    user.llm_tokens_this_month += tokens_used
    db.commit()
    return text


# --- OpenAI -----------------------------------------------------------------


def _openai_client():
    from openai import OpenAI

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise CommentaryError("OPENAI_API_KEY is not set")
    return OpenAI(api_key=api_key)


def _call_openai(user_prompt: str, max_tokens: int) -> tuple[str, int]:
    """Return (text, total_tokens_used)."""
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    try:
        client = _openai_client()
        resp = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
    except CommentaryError:
        raise
    except Exception as e:
        raise CommentaryError(f"OpenAI call failed: {e}") from e

    text = (resp.choices[0].message.content or "").strip()
    if not text:
        raise CommentaryError("OpenAI returned an empty response.")
    usage = getattr(resp, "usage", None)
    tokens = int(getattr(usage, "total_tokens", 0)) if usage else 0
    return text, tokens


# --- Anthropic --------------------------------------------------------------


def _anthropic_client():
    from anthropic import Anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise CommentaryError("ANTHROPIC_API_KEY is not set")
    return Anthropic(api_key=api_key)


def _call_anthropic(user_prompt: str, max_tokens: int) -> tuple[str, int]:
    """Return (text, total_tokens_used)."""
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    try:
        client = _anthropic_client()
        msg = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except CommentaryError:
        raise
    except Exception as e:
        raise CommentaryError(f"Anthropic call failed: {e}") from e

    # Anthropic returns a list of content blocks; only TextBlocks carry .text.
    parts = [getattr(b, "text", "") for b in (msg.content or [])]
    text = "\n".join(p for p in parts if p).strip()
    if not text:
        raise CommentaryError("Anthropic returned an empty response.")
    usage = getattr(msg, "usage", None)
    tokens = 0
    if usage is not None:
        tokens = int(getattr(usage, "input_tokens", 0)) + int(
            getattr(usage, "output_tokens", 0)
        )
    return text, tokens
