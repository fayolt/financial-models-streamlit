"""Unit tests for the Mailgun client. Fully mocked — never hits the real API."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.email.client import EmailError, send_email, send_email_best_effort
from app.email.templates import password_reset_email, welcome_email


@pytest.fixture(autouse=True)
def _set_mailgun(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAILGUN_API_KEY", "key-unit-test")
    monkeypatch.setenv("MAILGUN_DOMAIN", "mg.example.com")
    monkeypatch.setenv("MAILGUN_API_BASE", "https://api.mailgun.net")
    monkeypatch.setenv("MAIL_FROM", "Numquants <hello@mg.example.com>")


def _ok_response():
    resp = MagicMock()
    resp.status_code = 200
    resp.text = '{"id": "msg-123", "message": "Queued. Thank you."}'
    return resp


def _http_error_response(status: int, body: str):
    resp = MagicMock()
    resp.status_code = status
    resp.text = body
    return resp


def test_send_email_posts_to_mailgun():
    with patch("app.email.client.httpx.Client") as MockClient:
        instance = MockClient.return_value.__enter__.return_value
        instance.post.return_value = _ok_response()

        send_email(
            to="user@example.com",
            subject="Hi",
            text="hello",
            html="<p>hello</p>",
        )

        instance.post.assert_called_once()
        call = instance.post.call_args
        url = call.args[0]
        assert url == "https://api.mailgun.net/v3/mg.example.com/messages"
        assert call.kwargs["auth"] == ("api", "key-unit-test")
        data = call.kwargs["data"]
        assert data["to"] == "user@example.com"
        assert data["subject"] == "Hi"
        assert data["text"] == "hello"
        assert data["html"] == "<p>hello</p>"
        assert data["from"] == "Numquants <hello@mg.example.com>"


def test_send_email_missing_config_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MAILGUN_API_KEY", raising=False)
    with pytest.raises(EmailError, match="not configured"):
        send_email(to="x@y.com", subject="x", text="x")


def test_send_email_http_error_raises():
    with patch("app.email.client.httpx.Client") as MockClient:
        instance = MockClient.return_value.__enter__.return_value
        instance.post.return_value = _http_error_response(401, "Unauthorized")
        with pytest.raises(EmailError, match="HTTP 401"):
            send_email(to="x@y.com", subject="x", text="x")


def test_send_email_network_error_wrapped():
    with patch("app.email.client.httpx.Client") as MockClient:
        MockClient.side_effect = RuntimeError("DNS failure")
        with pytest.raises(EmailError, match="Mailgun call failed"):
            send_email(to="x@y.com", subject="x", text="x")


def test_send_email_best_effort_swallows_errors(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MAILGUN_API_KEY", raising=False)
    # No raise; returns False.
    assert send_email_best_effort(to="x@y.com", subject="x", text="x") is False


def test_send_email_best_effort_returns_true_on_success():
    with patch("app.email.client.httpx.Client") as MockClient:
        instance = MockClient.return_value.__enter__.return_value
        instance.post.return_value = _ok_response()
        assert send_email_best_effort(to="x@y.com", subject="x", text="x") is True


# --- template smoke tests ---------------------------------------------------


def test_welcome_email_includes_name_and_url():
    subject, text, html = welcome_email(
        recipient_email="user@example.com",
        full_name="Jane Doe",
        app_url="https://numquants.example.com",
    )
    assert "Welcome" in subject
    assert "Jane Doe" in text
    assert "https://numquants.example.com/pricing" in text
    assert "Jane Doe" in html
    assert "https://numquants.example.com/pricing" in html


def test_welcome_email_falls_back_to_email_prefix():
    _, text, _ = welcome_email(
        recipient_email="alice@example.com",
        full_name=None,
        app_url="https://numquants.example.com",
    )
    assert "Hi alice," in text


def test_password_reset_email_carries_link_and_ttl():
    subject, text, html = password_reset_email(
        recipient_email="user@example.com",
        reset_link="https://numquants.example.com/?reset_token=abc",
        ttl_minutes=60,
    )
    assert "Reset" in subject
    assert "https://numquants.example.com/?reset_token=abc" in text
    assert "60 minutes" in text
    assert "https://numquants.example.com/?reset_token=abc" in html
