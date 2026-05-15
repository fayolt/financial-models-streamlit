"""LLM-generated executive commentary for financial-model outputs.

Used by plugins that opt in (currently biotech and chicken-farming).
Reads OPENAI_API_KEY and OPENAI_MODEL at call time so tests can patch.

This is an Enterprise-tier feature. The orchestrator decides whether to
expose the "Generate AI commentary" button based on user.tier; this
module is a thin wrapper that doesn't enforce gating itself.
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


class CommentaryError(RuntimeError):
    """Raised when LLM commentary generation fails."""


def _client():
    """Create an OpenAI client, reading the API key at call time."""
    from openai import OpenAI

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise CommentaryError("OPENAI_API_KEY is not set")
    return OpenAI(api_key=api_key)


def _model_name() -> str:
    return os.environ.get("OPENAI_MODEL", "gpt-4o-mini")


def generate_commentary(
    *,
    plugin_name: str,
    description: str,
    summary: dict[str, Any],
    max_tokens: int = 600,
) -> str:
    """Generate executive commentary for one plugin's results.

    `summary` should be a small dict of label→value pairs describing the
    headline metrics and the key inputs. Keep it focused; LLMs do not
    benefit from raw data dumps.
    """
    user_prompt = (
        f"Model: {plugin_name}\n"
        f"Description: {description}\n\n"
        f"Key metrics and inputs:\n"
        f"{json.dumps(summary, default=str, indent=2)}\n\n"
        f"Write the commentary."
    )

    try:
        client = _client()
        resp = client.chat.completions.create(
            model=_model_name(),
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
    except CommentaryError:
        raise
    except Exception as e:
        raise CommentaryError(f"LLM call failed: {e}") from e

    text = (resp.choices[0].message.content or "").strip()
    if not text:
        raise CommentaryError("LLM returned an empty response.")
    return text
