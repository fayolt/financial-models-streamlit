"""Integration tests for signup / login / logout / get_current_user.

Requires Postgres reachable at DATABASE_URL (defaults to the docker-compose
container at localhost:5433). Skipped if the database is unreachable.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.service import AuthError, get_current_user, login, logout, signup
from app.db import engine
from app.db.models import Session as SessionRow


def _has_db() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _has_db(), reason="No Postgres reachable")


@pytest.fixture
def db():
    """Session with savepoint isolation: every commit inside is rolled back."""
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


# --- signup --------------------------------------------------------------------


def test_signup_creates_user(db: Session):
    user = signup(db, email="alice@example.com", password="strongpass1")
    assert user.email == "alice@example.com"
    assert user.tier == "free"
    assert user.password_hash.startswith("$argon2")


def test_signup_normalises_email(db: Session):
    user = signup(db, email="  Bob@Example.COM ", password="strongpass1")
    assert user.email == "bob@example.com"


def test_signup_rejects_duplicate_email(db: Session):
    signup(db, email="carol@example.com", password="strongpass1")
    with pytest.raises(AuthError, match="already in use"):
        signup(db, email="carol@example.com", password="otherpass2")


def test_signup_rejects_short_password(db: Session):
    with pytest.raises(AuthError, match="at least 8"):
        signup(db, email="dave@example.com", password="short")


def test_signup_rejects_invalid_email(db: Session):
    with pytest.raises(AuthError, match="valid email"):
        signup(db, email="not-an-email", password="strongpass1")


# --- login ---------------------------------------------------------------------


def test_login_roundtrip(db: Session):
    signup(db, email="ed@example.com", password="strongpass1")
    user, token = login(db, email="ed@example.com", password="strongpass1")
    assert user.email == "ed@example.com"
    assert isinstance(token, str) and len(token) > 0


def test_login_normalises_email_case(db: Session):
    signup(db, email="fran@example.com", password="strongpass1")
    user, _ = login(db, email="FRAN@EXAMPLE.COM", password="strongpass1")
    assert user.email == "fran@example.com"


def test_login_rejects_wrong_password(db: Session):
    signup(db, email="grace@example.com", password="strongpass1")
    with pytest.raises(AuthError, match="Invalid credentials"):
        login(db, email="grace@example.com", password="wrongpass1")


def test_login_rejects_unknown_email(db: Session):
    with pytest.raises(AuthError, match="Invalid credentials"):
        login(db, email="ghost@example.com", password="anything12")


def test_login_creates_active_session_row(db: Session):
    signup(db, email="hank@example.com", password="strongpass1")
    user, _ = login(db, email="hank@example.com", password="strongpass1")
    rows = db.query(SessionRow).filter_by(user_id=user.id).all()
    assert len(rows) == 1
    assert rows[0].revoked_at is None


# --- get_current_user ---------------------------------------------------------


def test_get_current_user_roundtrip(db: Session):
    signup(db, email="ivy@example.com", password="strongpass1")
    user, token = login(db, email="ivy@example.com", password="strongpass1")
    fetched = get_current_user(db, token)
    assert fetched is not None
    assert fetched.id == user.id


def test_get_current_user_rejects_missing_token(db: Session):
    assert get_current_user(db, None) is None
    assert get_current_user(db, "") is None


def test_get_current_user_rejects_garbage_token(db: Session):
    assert get_current_user(db, "not-a-jwt-at-all") is None


# --- logout -------------------------------------------------------------------


def test_logout_revokes_session(db: Session):
    signup(db, email="jane@example.com", password="strongpass1")
    _, token = login(db, email="jane@example.com", password="strongpass1")
    assert get_current_user(db, token) is not None
    logout(db, token)
    assert get_current_user(db, token) is None


def test_logout_silent_on_unknown_token(db: Session):
    logout(db, None)  # should not raise
    logout(db, "")    # should not raise


def test_logout_idempotent(db: Session):
    signup(db, email="kim@example.com", password="strongpass1")
    _, token = login(db, email="kim@example.com", password="strongpass1")
    logout(db, token)
    logout(db, token)  # second call is a no-op
