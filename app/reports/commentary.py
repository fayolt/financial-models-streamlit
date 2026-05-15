"""LLM-generated executive commentary for financial-model outputs.

Two providers are wired: OpenAI (default) and Anthropic. The active provider
is picked by `LLM_PROVIDER` env var ("openai" or "anthropic"). All env vars
are read at call time so tests can monkey-patch them per case.

Used by plugins that opt in (currently biotech and chicken-farming).
"""
from __future__ import annotations

import json
import os
from typing import Any


SYSTEM_PROMPT = """You are a senior financial analyst writing executive commentary on a financial model output for an investor audience. Write 2-3 short paragraphs that:

- Open with the headline result (good, bad, or neutral) in plain language.
- Discuss 2-3 key drivers behind the result.
- Flag 1-2 risks or sensitivities the investor should know about.

Be concise (target ~200 words). Interpret the numbers rather than restating them verbatim. Write flowing prose, not bullet lists. Avoid markdown formatting."""


_VALID_PROVIDERS = ("openai", "anthropic")


class CommentaryError(RuntimeError):
    """Raised when LLM commentary generation fails."""


def _provider() -> str:
    return os.environ.get("LLM_PROVIDER", "openai").strip().lower()


def generate_commentary(
    *,
    plugin_name: str,
    description: str,
    summary: dict[str, Any],
    max_tokens: int = 600,
) -> str:
    """Generate executive commentary for one plugin's results.

    `summary` should be a small dict of label→value pairs describing the
    headline metrics and key inputs. Don't dump raw data — LLMs do better
    with curated context.
    """
    user_prompt = (
        f"Model: {plugin_name}\n"
        f"Description: {description}\n\n"
        f"Key metrics and inputs:\n"
        f"{json.dumps(summary, default=str, indent=2)}\n\n"
        f"Write the commentary."
    )

    provider = _provider()
    if provider == "openai":
        return _call_openai(user_prompt, max_tokens)
    if provider == "anthropic":
        return _call_anthropic(user_prompt, max_tokens)
    raise CommentaryError(
        f"Unknown LLM_PROVIDER: {provider!r}. "
        f"Expected one of: {', '.join(_VALID_PROVIDERS)}."
    )


# --- OpenAI -----------------------------------------------------------------


def _openai_client():
    from openai import OpenAI

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise CommentaryError("OPENAI_API_KEY is not set")
    return OpenAI(api_key=api_key)


def _call_openai(user_prompt: str, max_tokens: int) -> str:
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
    return text


# --- Anthropic --------------------------------------------------------------


def _anthropic_client():
    from anthropic import Anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise CommentaryError("ANTHROPIC_API_KEY is not set")
    return Anthropic(api_key=api_key)


def _call_anthropic(user_prompt: str, max_tokens: int) -> str:
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
    return text
