"""Unit tests for the commentary service. Fully mocked — never hits a real API."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.reports.commentary import (
    SYSTEM_PROMPT,
    CommentaryError,
    generate_commentary,
)


# --- helpers ----------------------------------------------------------------


def _fake_openai_response(text: str):
    msg = MagicMock()
    msg.content = text
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _fake_anthropic_response(text: str):
    block = MagicMock()
    block.text = text
    msg = MagicMock()
    msg.content = [block]
    return msg


# --- dispatch ---------------------------------------------------------------


def test_unknown_provider_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_PROVIDER", "cohere")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    with pytest.raises(CommentaryError, match="Unknown LLM_PROVIDER"):
        generate_commentary(plugin_name="x", description="d", summary={})


def test_default_provider_is_openai(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_openai_response("ok")
    with patch("app.reports.commentary._openai_client", return_value=fake_client):
        text = generate_commentary(plugin_name="x", description="d", summary={})
    assert text == "ok"


# --- OpenAI path ------------------------------------------------------------


def test_openai_missing_key_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(CommentaryError, match="OPENAI_API_KEY"):
        generate_commentary(plugin_name="x", description="d", summary={})


def test_openai_generates_text(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_openai_response(
        "Commentary text from the LLM."
    )

    with patch("app.reports.commentary._openai_client", return_value=fake_client):
        text = generate_commentary(
            plugin_name="Test Model",
            description="A test plugin.",
            summary={"NPV": 1_000_000, "IRR": 0.18},
        )

    assert text == "Commentary text from the LLM."
    kwargs = fake_client.chat.completions.create.call_args.kwargs
    messages = kwargs["messages"]
    assert messages[0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert messages[1]["role"] == "user"
    assert "Test Model" in messages[1]["content"]
    assert "NPV" in messages[1]["content"]


def test_openai_strips_whitespace(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_openai_response(
        "  \n\nGood result.\n\n  "
    )
    with patch("app.reports.commentary._openai_client", return_value=fake_client):
        text = generate_commentary(plugin_name="x", description="d", summary={})
    assert text == "Good result."


def test_openai_empty_response_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_openai_response("")
    with patch("app.reports.commentary._openai_client", return_value=fake_client):
        with pytest.raises(CommentaryError, match="empty"):
            generate_commentary(plugin_name="x", description="d", summary={})


def test_openai_api_error_wrapped(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = RuntimeError("API down")
    with patch("app.reports.commentary._openai_client", return_value=fake_client):
        with pytest.raises(CommentaryError, match="OpenAI call failed"):
            generate_commentary(plugin_name="x", description="d", summary={})


def test_openai_uses_model_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_openai_response("ok")
    with patch("app.reports.commentary._openai_client", return_value=fake_client):
        generate_commentary(plugin_name="x", description="d", summary={})
    assert fake_client.chat.completions.create.call_args.kwargs["model"] == "gpt-4o"


# --- Anthropic path ---------------------------------------------------------


def test_anthropic_missing_key_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(CommentaryError, match="ANTHROPIC_API_KEY"):
        generate_commentary(plugin_name="x", description="d", summary={})


def test_anthropic_generates_text(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_anthropic_response(
        "Commentary from Claude."
    )

    with patch("app.reports.commentary._anthropic_client", return_value=fake_client):
        text = generate_commentary(
            plugin_name="Test Model",
            description="A test plugin.",
            summary={"NPV": 1_000_000},
        )

    assert text == "Commentary from Claude."
    kwargs = fake_client.messages.create.call_args.kwargs
    # Anthropic uses a top-level `system` argument, not a messages role.
    assert kwargs["system"] == SYSTEM_PROMPT
    user_messages = kwargs["messages"]
    assert user_messages[0]["role"] == "user"
    assert "Test Model" in user_messages[0]["content"]
    assert "NPV" in user_messages[0]["content"]


def test_anthropic_joins_multiple_text_blocks(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    fake_client = MagicMock()
    block_a, block_b = MagicMock(), MagicMock()
    block_a.text = "First paragraph."
    block_b.text = "Second paragraph."
    msg = MagicMock()
    msg.content = [block_a, block_b]
    fake_client.messages.create.return_value = msg

    with patch("app.reports.commentary._anthropic_client", return_value=fake_client):
        text = generate_commentary(plugin_name="x", description="d", summary={})
    assert text == "First paragraph.\nSecond paragraph."


def test_anthropic_empty_response_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_anthropic_response("")
    with patch("app.reports.commentary._anthropic_client", return_value=fake_client):
        with pytest.raises(CommentaryError, match="empty"):
            generate_commentary(plugin_name="x", description="d", summary={})


def test_anthropic_api_error_wrapped(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    fake_client = MagicMock()
    fake_client.messages.create.side_effect = RuntimeError("Anthropic API down")
    with patch("app.reports.commentary._anthropic_client", return_value=fake_client):
        with pytest.raises(CommentaryError, match="Anthropic call failed"):
            generate_commentary(plugin_name="x", description="d", summary={})


def test_anthropic_uses_model_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-4-7")
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_anthropic_response("ok")
    with patch("app.reports.commentary._anthropic_client", return_value=fake_client):
        generate_commentary(plugin_name="x", description="d", summary={})
    assert fake_client.messages.create.call_args.kwargs["model"] == "claude-opus-4-7"
