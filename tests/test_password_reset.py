"""Integration tests for the password-reset flow against the live DB."""
from __future__ import annotations

import time
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.passwords import verify_password
from app.auth.service import (
    AuthError,
    complete_password_reset,
    login,
    request_password_reset,
    signup,
)
from app.auth.tokens import (
    InvalidTokenError,
    issue_reset_token,
    issue_session_token,
    verify_reset_token,
    verify_session_token,
)
from app.db import engine
from app.db.models import Session as SessionRow


def _has_db() -> bool:
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _has_db(), reason="No Postgres reachable")


@pytest.fixture
def db():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


# --- reset-token primitives --------------------------------------------------


def test_reset_token_roundtrip():
    user_id = uuid.uuid4()
    token, _ = issue_reset_token(user_id=user_id)
    assert verify_reset_token(token) == user_id


def test_reset_token_rejects_session_token():
    """A session JWT must not double as a reset token."""
    user_id = uuid.uuid4()
    session_jwt, _ = issue_session_token(user_id=user_id, email="x@y.com")
    with pytest.raises(InvalidTokenError, match="not a password-reset"):
        verify_reset_token(session_jwt)


def test_session_verify_rejects_reset_token():
    """A reset token must not be accepted as a session."""
    user_id = uuid.uuid4()
    reset_token, _ = issue_reset_token(user_id=user_id)
    with pytest.raises(InvalidTokenError, match="purpose"):
        verify_session_token(reset_token)


def test_reset_token_expired():
    user_id = uuid.uuid4()
    token, _ = issue_reset_token(user_id=user_id, ttl_seconds=-1)
    with pytest.raises(InvalidTokenError):
        verify_reset_token(token)


# --- service-level flow ------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_email(monkeypatch: pytest.MonkeyPatch):
    """Don't hit Mailgun during these tests."""
    monkeypatch.setenv("MAILGUN_API_KEY", "")  # forces best-effort failure
    yield


def test_request_password_reset_returns_true_for_unknown_email(db: Session):
    """Silent for unknown emails to avoid disclosing whether an account exists."""
    assert request_password_reset(db, email="nobody@example.com") is True


def test_request_password_reset_sends_email_for_known_user(db: Session, monkeypatch: pytest.MonkeyPatch):
    signup(db, email="alice@example.com", password="strongpass1")
    monkeypatch.setenv("MAILGUN_API_KEY", "key-test")
    monkeypatch.setenv("MAILGUN_DOMAIN", "mg.example.com")
    monkeypatch.setenv("MAIL_FROM", "Zenkos <hello@mg.example.com>")
    monkeypatch.setenv("APP_BASE_URL", "https://zenkos.example.com")

    with patch("app.email.client.httpx.Client") as MockClient:
        instance = MockClient.return_value.__enter__.return_value
        resp = type("R", (), {"status_code": 200, "text": "ok"})()
        instance.post.return_value = resp

        request_password_reset(db, email="alice@example.com")

        instance.post.assert_called_once()
        sent = instance.post.call_args.kwargs["data"]
        assert sent["to"] == "alice@example.com"
        assert "reset_token=" in sent["text"]
        assert "https://zenkos.example.com" in sent["text"]


def test_complete_password_reset_updates_hash(db: Session):
    user = signup(db, email="bob@example.com", password="originalpass1")
    token, _ = issue_reset_token(user_id=user.id)

    complete_password_reset(db, token=token, new_password="brandnewpass2")

    # Old password fails, new password works.
    with pytest.raises(AuthError):
        login(db, email="bob@example.com", password="originalpass1")
    refreshed, _ = login(db, email="bob@example.com", password="brandnewpass2")
    assert refreshed.id == user.id
    assert verify_password(refreshed.password_hash, "brandnewpass2")


def test_complete_password_reset_rejects_short_password(db: Session):
    user = signup(db, email="carol@example.com", password="originalpass1")
    token, _ = issue_reset_token(user_id=user.id)
    with pytest.raises(AuthError, match="at least 8"):
        complete_password_reset(db, token=token, new_password="short")


def test_complete_password_reset_rejects_invalid_token(db: Session):
    signup(db, email="dave@example.com", password="originalpass1")
    with pytest.raises(AuthError, match="invalid or expired"):
        complete_password_reset(db, token="not-a-jwt", new_password="newpass1234")


def test_complete_password_reset_revokes_existing_sessions(db: Session):
    user = signup(db, email="ed@example.com", password="originalpass1")
    _, login_token = login(db, email="ed@example.com", password="originalpass1")

    # Sanity: there's an active session row.
    active = (
        db.query(SessionRow)
        .filter_by(user_id=user.id)
        .filter(SessionRow.revoked_at.is_(None))
        .all()
    )
    assert len(active) == 1

    reset_token, _ = issue_reset_token(user_id=user.id)
    complete_password_reset(db, token=reset_token, new_password="newpass1234")

    # All sessions should now be revoked.
    still_active = (
        db.query(SessionRow)
        .filter_by(user_id=user.id)
        .filter(SessionRow.revoked_at.is_(None))
        .all()
    )
    assert len(still_active) == 0
