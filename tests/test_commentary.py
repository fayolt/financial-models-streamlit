"""Unit tests for the commentary service. Fully mocked — never hits a real API."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.reports.commentary import (
    SYSTEM_PROMPT,
    CommentaryError,
    generate_commentary,
)


# --- helpers ----------------------------------------------------------------


def _fake_openai_response(text: str, tokens: int = 100):
    msg = MagicMock()
    msg.content = text
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = MagicMock(total_tokens=tokens)
    return resp


def _fake_anthropic_response(text: str, input_tokens: int = 50, output_tokens: int = 50):
    block = MagicMock()
    block.text = text
    msg = MagicMock()
    msg.content = [block]
    msg.usage = MagicMock(input_tokens=input_tokens, output_tokens=output_tokens)
    return msg


@pytest.fixture
def fake_user_db():
    """Return (db_mock, user_id) where `db_mock.get(User, ...)` returns an
    Enterprise user with plenty of quota remaining. Tests can adjust the
    `tier` or `llm_tokens_this_month` attrs on the returned user as needed."""
    user_id = uuid4()
    user = MagicMock()
    user.id = user_id
    user.tier = "enterprise"
    user.llm_tokens_this_month = 0
    user.llm_tokens_month_reset_at = None

    db = MagicMock()
    db.get.return_value = user
    # Make commit() update user.llm_tokens_month_reset_at if not set — closer
    # to real behaviour but not strictly needed by these tests.
    return db, user_id, user


def _gc(db, user_id, **kwargs):
    """Shorthand: invoke generate_commentary with sensible defaults."""
    return generate_commentary(
        db=db,
        user_id=user_id,
        plugin_name=kwargs.pop("plugin_name", "x"),
        description=kwargs.pop("description", "d"),
        summary=kwargs.pop("summary", {}),
        **kwargs,
    )


# --- dispatch ---------------------------------------------------------------


def test_unknown_provider_raises(monkeypatch: pytest.MonkeyPatch, fake_user_db):
    db, user_id, _ = fake_user_db
    monkeypatch.setenv("LLM_PROVIDER", "cohere")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    with pytest.raises(CommentaryError, match="Unknown LLM_PROVIDER"):
        _gc(db, user_id)


def test_default_provider_is_openai(monkeypatch: pytest.MonkeyPatch, fake_user_db):
    db, user_id, _ = fake_user_db
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_openai_response("ok")
    with patch("app.reports.commentary._openai_client", return_value=fake_client):
        text = _gc(db, user_id)
    assert text == "ok"


# --- OpenAI path ------------------------------------------------------------


def test_openai_missing_key_raises(monkeypatch: pytest.MonkeyPatch, fake_user_db):
    db, user_id, _ = fake_user_db
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(CommentaryError, match="OPENAI_API_KEY"):
        _gc(db, user_id)


def test_openai_generates_text(monkeypatch: pytest.MonkeyPatch, fake_user_db):
    db, user_id, _ = fake_user_db
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_openai_response(
        "Commentary text from the LLM."
    )

    with patch("app.reports.commentary._openai_client", return_value=fake_client):
        text = _gc(
            db, user_id,
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


def test_openai_strips_whitespace(monkeypatch: pytest.MonkeyPatch, fake_user_db):
    db, user_id, _ = fake_user_db
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_openai_response(
        "  \n\nGood result.\n\n  "
    )
    with patch("app.reports.commentary._openai_client", return_value=fake_client):
        text = _gc(db, user_id)
    assert text == "Good result."


def test_openai_empty_response_raises(monkeypatch: pytest.MonkeyPatch, fake_user_db):
    db, user_id, _ = fake_user_db
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_openai_response("")
    with patch("app.reports.commentary._openai_client", return_value=fake_client):
        with pytest.raises(CommentaryError, match="empty"):
            _gc(db, user_id)


def test_openai_api_error_wrapped(monkeypatch: pytest.MonkeyPatch, fake_user_db):
    db, user_id, _ = fake_user_db
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = RuntimeError("API down")
    with patch("app.reports.commentary._openai_client", return_value=fake_client):
        with pytest.raises(CommentaryError, match="OpenAI call failed"):
            _gc(db, user_id)


def test_openai_uses_model_from_env(monkeypatch: pytest.MonkeyPatch, fake_user_db):
    db, user_id, _ = fake_user_db
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_openai_response("ok")
    with patch("app.reports.commentary._openai_client", return_value=fake_client):
        _gc(db, user_id)
    assert fake_client.chat.completions.create.call_args.kwargs["model"] == "gpt-4o"


# --- Anthropic path ---------------------------------------------------------


def test_anthropic_missing_key_raises(monkeypatch: pytest.MonkeyPatch, fake_user_db):
    db, user_id, _ = fake_user_db
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(CommentaryError, match="ANTHROPIC_API_KEY"):
        _gc(db, user_id)


def test_anthropic_generates_text(monkeypatch: pytest.MonkeyPatch, fake_user_db):
    db, user_id, _ = fake_user_db
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_anthropic_response(
        "Commentary from Claude."
    )

    with patch("app.reports.commentary._anthropic_client", return_value=fake_client):
        text = _gc(
            db, user_id,
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


def test_anthropic_joins_multiple_text_blocks(monkeypatch: pytest.MonkeyPatch, fake_user_db):
    db, user_id, _ = fake_user_db
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    fake_client = MagicMock()
    block_a, block_b = MagicMock(), MagicMock()
    block_a.text = "First paragraph."
    block_b.text = "Second paragraph."
    msg = MagicMock()
    msg.content = [block_a, block_b]
    msg.usage = MagicMock(input_tokens=50, output_tokens=50)
    fake_client.messages.create.return_value = msg

    with patch("app.reports.commentary._anthropic_client", return_value=fake_client):
        text = _gc(db, user_id)
    assert text == "First paragraph.\nSecond paragraph."


def test_anthropic_empty_response_raises(monkeypatch: pytest.MonkeyPatch, fake_user_db):
    db, user_id, _ = fake_user_db
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_anthropic_response("")
    with patch("app.reports.commentary._anthropic_client", return_value=fake_client):
        with pytest.raises(CommentaryError, match="empty"):
            _gc(db, user_id)


def test_anthropic_api_error_wrapped(monkeypatch: pytest.MonkeyPatch, fake_user_db):
    db, user_id, _ = fake_user_db
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    fake_client = MagicMock()
    fake_client.messages.create.side_effect = RuntimeError("Anthropic API down")
    with patch("app.reports.commentary._anthropic_client", return_value=fake_client):
        with pytest.raises(CommentaryError, match="Anthropic call failed"):
            _gc(db, user_id)


def test_anthropic_uses_model_from_env(monkeypatch: pytest.MonkeyPatch, fake_user_db):
    db, user_id, _ = fake_user_db
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-4-7")
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_anthropic_response("ok")
    with patch("app.reports.commentary._anthropic_client", return_value=fake_client):
        _gc(db, user_id)
    assert fake_client.messages.create.call_args.kwargs["model"] == "claude-opus-4-7"


# --- Quota enforcement ------------------------------------------------------


def test_free_tier_blocked(monkeypatch: pytest.MonkeyPatch, fake_user_db):
    db, user_id, user = fake_user_db
    user.tier = "free"
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    with pytest.raises(CommentaryError, match="not included in your tier"):
        _gc(db, user_id)


def test_quota_exhausted_blocks_call(monkeypatch: pytest.MonkeyPatch, fake_user_db):
    db, user_id, user = fake_user_db
    user.tier = "enterprise"
    user.llm_tokens_this_month = 1_000_000  # well over the 500k Enterprise cap
    from datetime import datetime, timezone
    user.llm_tokens_month_reset_at = datetime.now(timezone.utc)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    with pytest.raises(CommentaryError, match="budget exhausted"):
        _gc(db, user_id)


def test_successful_call_increments_token_count(monkeypatch: pytest.MonkeyPatch, fake_user_db):
    db, user_id, user = fake_user_db
    user.tier = "enterprise"
    user.llm_tokens_this_month = 0
    from datetime import datetime, timezone
    user.llm_tokens_month_reset_at = datetime.now(timezone.utc)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_openai_response("ok", tokens=250)
    with patch("app.reports.commentary._openai_client", return_value=fake_client):
        _gc(db, user_id)
    assert user.llm_tokens_this_month == 250
