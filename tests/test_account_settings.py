"""Integration tests for change_password / update_profile / delete_account."""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.passwords import verify_password
from app.auth.service import (
    AuthError,
    change_password,
    delete_account,
    login,
    signup,
    update_profile,
)
from app.db import engine
from app.db.models import Plan, Session as SessionRow, Subscription, User


def _has_db() -> bool:
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _has_db(), reason="No Postgres reachable")


@pytest.fixture(autouse=True)
def _no_mailgun(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAILGUN_API_KEY", "")  # forces best-effort no-op


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


# --- change_password --------------------------------------------------------


def test_change_password_roundtrip(db: Session):
    user = signup(db, email="alice@example.com", password="originalpass1")
    change_password(
        db,
        user_id=user.id,
        current_password="originalpass1",
        new_password="brandnewpass2",
    )
    refreshed, _ = login(db, email="alice@example.com", password="brandnewpass2")
    assert refreshed.id == user.id
    assert verify_password(refreshed.password_hash, "brandnewpass2")


def test_change_password_rejects_wrong_current(db: Session):
    user = signup(db, email="bob@example.com", password="originalpass1")
    with pytest.raises(AuthError, match="incorrect"):
        change_password(
            db,
            user_id=user.id,
            current_password="wrongpass1",
            new_password="brandnewpass2",
        )


def test_change_password_rejects_short_new(db: Session):
    user = signup(db, email="carol@example.com", password="originalpass1")
    with pytest.raises(AuthError, match="at least 8"):
        change_password(
            db,
            user_id=user.id,
            current_password="originalpass1",
            new_password="short",
        )


def test_change_password_rejects_unchanged(db: Session):
    user = signup(db, email="dave@example.com", password="originalpass1")
    with pytest.raises(AuthError, match="differ"):
        change_password(
            db,
            user_id=user.id,
            current_password="originalpass1",
            new_password="originalpass1",
        )


def test_change_password_revokes_other_sessions(db: Session):
    user = signup(db, email="ed@example.com", password="originalpass1")
    _, t_a = login(db, email="ed@example.com", password="originalpass1")
    _, t_b = login(db, email="ed@example.com", password="originalpass1")
    assert (
        db.query(SessionRow)
        .filter_by(user_id=user.id)
        .filter(SessionRow.revoked_at.is_(None))
        .count()
        == 2
    )

    # Keep t_a, revoke everything else.
    change_password(
        db,
        user_id=user.id,
        current_password="originalpass1",
        new_password="brandnewpass2",
        keep_current_session_token=t_a,
    )

    from app.auth.tokens import token_hash

    surviving = (
        db.query(SessionRow)
        .filter_by(user_id=user.id)
        .filter(SessionRow.revoked_at.is_(None))
        .all()
    )
    assert len(surviving) == 1
    assert surviving[0].token_hash == token_hash(t_a)


# --- update_profile ---------------------------------------------------------


def test_update_profile_sets_full_name(db: Session):
    user = signup(db, email="fran@example.com", password="originalpass1")
    update_profile(db, user_id=user.id, full_name="Fran Smith")
    refreshed = db.get(User, user.id)
    assert refreshed.full_name == "Fran Smith"


def test_update_profile_empty_string_clears_name(db: Session):
    user = signup(db, email="grace@example.com", password="originalpass1", full_name="Old")
    update_profile(db, user_id=user.id, full_name="   ")
    refreshed = db.get(User, user.id)
    assert refreshed.full_name is None


def test_update_profile_unknown_user_raises(db: Session):
    with pytest.raises(AuthError):
        update_profile(db, user_id=uuid.uuid4(), full_name="Nobody")


# --- delete_account ---------------------------------------------------------


def test_delete_account_removes_user(db: Session):
    user = signup(db, email="hank@example.com", password="originalpass1")
    user_id = user.id
    delete_account(db, user_id=user_id, password_confirm="originalpass1")
    assert db.get(User, user_id) is None


def test_delete_account_rejects_wrong_password(db: Session):
    user = signup(db, email="ivy@example.com", password="originalpass1")
    with pytest.raises(AuthError, match="Password is incorrect"):
        delete_account(db, user_id=user.id, password_confirm="wrongpass1")
    assert db.get(User, user.id) is not None


def test_delete_account_cascades_sessions(db: Session):
    user = signup(db, email="jane@example.com", password="originalpass1")
    login(db, email="jane@example.com", password="originalpass1")
    assert db.query(SessionRow).filter_by(user_id=user.id).count() == 1

    delete_account(db, user_id=user.id, password_confirm="originalpass1")
    assert db.query(SessionRow).filter_by(user_id=user.id).count() == 0


def test_delete_account_disables_paystack_subscription(db: Session):
    user = signup(db, email="kim@example.com", password="originalpass1")
    plan = Plan(
        slug=f"pro-{uuid.uuid4().hex[:6]}",
        name="Pro",
        tier="pro",
        paystack_plan_code=f"PLN_{uuid.uuid4().hex[:8]}",
        monthly_price_minor_units=1_500_000,
        currency="NGN",
    )
    db.add(plan)
    db.commit()
    sub = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        status="active",
        paystack_subscription_code=f"SUB_{uuid.uuid4().hex[:8]}",
    )
    db.add(sub)
    db.commit()
    sub_code = sub.paystack_subscription_code

    with patch("api.paystack.disable_subscription") as mock_disable:
        delete_account(db, user_id=user.id, password_confirm="originalpass1")
        # Should have called Paystack disable before deleting the user.
        mock_disable.assert_called_once_with(sub_code)
    assert db.get(User, user.id) is None


def test_delete_account_proceeds_even_if_paystack_fails(db: Session):
    user = signup(db, email="leo@example.com", password="originalpass1")
    plan = Plan(
        slug=f"pro-{uuid.uuid4().hex[:6]}",
        name="Pro",
        tier="pro",
        paystack_plan_code=f"PLN_{uuid.uuid4().hex[:8]}",
        monthly_price_minor_units=1_500_000,
        currency="NGN",
    )
    db.add(plan)
    db.commit()
    sub = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        status="active",
        paystack_subscription_code=f"SUB_{uuid.uuid4().hex[:8]}",
    )
    db.add(sub)
    db.commit()

    with patch(
        "api.paystack.disable_subscription",
        side_effect=RuntimeError("Paystack down"),
    ):
        delete_account(db, user_id=user.id, password_confirm="originalpass1")
    assert db.get(User, user.id) is None
