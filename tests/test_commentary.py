"""Unit tests for the OpenAI commentary service. Fully mocked — never hits the real API."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.reports.commentary import (
    SYSTEM_PROMPT,
    CommentaryError,
    generate_commentary,
)


def _fake_response(text: str):
    msg = MagicMock()
    msg.content = text
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(CommentaryError, match="OPENAI_API_KEY"):
        generate_commentary(plugin_name="x", description="d", summary={})


def test_generates_text_from_openai(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_response(
        "Commentary text from the LLM."
    )

    with patch("app.reports.commentary._client", return_value=fake_client):
        text = generate_commentary(
            plugin_name="Test Model",
            description="A test plugin.",
            summary={"NPV": 1_000_000, "IRR": 0.18},
        )

    assert text == "Commentary text from the LLM."
    create_kwargs = fake_client.chat.completions.create.call_args.kwargs
    messages = create_kwargs["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == SYSTEM_PROMPT
    assert messages[1]["role"] == "user"
    assert "Test Model" in messages[1]["content"]
    assert "NPV" in messages[1]["content"]


def test_strips_whitespace(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_response(
        "  \n\nGood result.\n\n  "
    )
    with patch("app.reports.commentary._client", return_value=fake_client):
        text = generate_commentary(
            plugin_name="x", description="d", summary={}
        )
    assert text == "Good result."


def test_empty_response_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_response("")
    with patch("app.reports.commentary._client", return_value=fake_client):
        with pytest.raises(CommentaryError, match="empty"):
            generate_commentary(plugin_name="x", description="d", summary={})


def test_api_error_wrapped(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = RuntimeError("API down")
    with patch("app.reports.commentary._client", return_value=fake_client):
        with pytest.raises(CommentaryError, match="LLM call failed"):
            generate_commentary(plugin_name="x", description="d", summary={})


def test_uses_model_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_response("ok")
    with patch("app.reports.commentary._client", return_value=fake_client):
        generate_commentary(plugin_name="x", description="d", summary={})
    assert fake_client.chat.completions.create.call_args.kwargs["model"] == "gpt-4o"
