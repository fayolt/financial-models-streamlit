"""Integration tests for admin service + analytics."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.admin import (
    NotAdminError,
    get_user_detail,
    list_users,
    mrr_minor_units,
    reports_by_model,
    require_admin,
    set_user_tier,
    signups_by_day,
    tier_distribution,
    total_active_users,
)
from app.auth.service import signup
from app.db import engine
from app.db.models import Plan, ReportRun, Subscription, User


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
    monkeypatch.setenv("MAILGUN_API_KEY", "")


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


# --- require_admin ----------------------------------------------------------


def test_require_admin_passes_for_admin():
    require_admin({"id": "x", "is_admin": True})  # no exception


def test_require_admin_rejects_non_admin():
    with pytest.raises(NotAdminError):
        require_admin({"id": "x", "is_admin": False})


def test_require_admin_rejects_missing_flag():
    with pytest.raises(NotAdminError):
        require_admin({"id": "x"})


def test_require_admin_rejects_none():
    with pytest.raises(NotAdminError):
        require_admin(None)


# --- list_users -------------------------------------------------------------


def test_list_users_returns_all(db: Session):
    a = signup(db, email="aaron@example.com", password="strongpass1")
    b = signup(db, email="beth@example.com", password="strongpass1")
    found = list_users(db, limit=200)
    ids = {u.id for u in found}
    assert a.id in ids
    assert b.id in ids


def test_list_users_search_filters_by_email(db: Session):
    signup(db, email="alpha@example.com", password="strongpass1")
    signup(db, email="bravo@example.com", password="strongpass1")
    just_alpha = list_users(db, search="alph")
    emails = {u.email for u in just_alpha}
    assert "alpha@example.com" in emails
    assert "bravo@example.com" not in emails


# --- get_user_detail --------------------------------------------------------


def test_get_user_detail_includes_subscriptions_and_runs(db: Session):
    user = signup(db, email="charlie@example.com", password="strongpass1")
    plan = Plan(
        slug=f"pro-{uuid.uuid4().hex[:6]}",
        name="Pro",
        tier="pro",
        monthly_price_minor_units=1_500_000,
        currency="NGN",
    )
    db.add(plan)
    db.commit()
    db.add(
        Subscription(
            user_id=user.id, plan_id=plan.id, status="active",
            paystack_subscription_code=f"SUB_{uuid.uuid4().hex[:8]}",
        )
    )
    db.add(
        ReportRun(
            user_id=user.id, model_slug="biotech", format="pdf",
            status="success", bytes_size=12345,
        )
    )
    db.commit()

    detail = get_user_detail(db, user.id)
    assert detail is not None
    assert detail["user"].id == user.id
    assert len(detail["subscriptions"]) == 1
    sub, sub_plan = detail["subscriptions"][0]
    assert sub.status == "active"
    assert sub_plan.tier == "pro"
    assert len(detail["recent_runs"]) == 1
    assert detail["recent_runs"][0].model_slug == "biotech"


def test_get_user_detail_returns_none_for_missing(db: Session):
    assert get_user_detail(db, uuid.uuid4()) is None


# --- set_user_tier ----------------------------------------------------------


def test_set_user_tier_updates(db: Session):
    user = signup(db, email="dana@example.com", password="strongpass1")
    set_user_tier(db, user.id, "enterprise")
    refreshed = db.get(User, user.id)
    assert refreshed.tier == "enterprise"


def test_set_user_tier_rejects_invalid(db: Session):
    user = signup(db, email="eve@example.com", password="strongpass1")
    with pytest.raises(ValueError, match="Invalid tier"):
        set_user_tier(db, user.id, "platinum")


def test_set_user_tier_unknown_user(db: Session):
    with pytest.raises(ValueError, match="not found"):
        set_user_tier(db, uuid.uuid4(), "pro")


# --- analytics --------------------------------------------------------------


def test_total_active_users_counts_only_active(db: Session):
    before = total_active_users(db)
    u = signup(db, email="frank@example.com", password="strongpass1")
    assert total_active_users(db) == before + 1
    u.is_active = False
    db.commit()
    assert total_active_users(db) == before


def test_tier_distribution_counts(db: Session):
    signup(db, email="gina@example.com", password="strongpass1")
    pro_user = signup(db, email="hank@example.com", password="strongpass1")
    set_user_tier(db, pro_user.id, "pro")
    dist = tier_distribution(db)
    # Other tests may have created users in the savepoint; we only assert lower bounds.
    assert dist.get("free", 0) >= 1
    assert dist.get("pro", 0) >= 1


def test_mrr_sums_active_subscriptions_only(db: Session):
    user = signup(db, email="ivy@example.com", password="strongpass1")
    plan = Plan(
        slug=f"pro-{uuid.uuid4().hex[:6]}",
        name="Pro",
        tier="pro",
        monthly_price_minor_units=1_500_000,
        currency="NGN",
    )
    db.add(plan)
    db.commit()
    # Cancelled subs should NOT count.
    db.add(Subscription(user_id=user.id, plan_id=plan.id, status="cancelled"))
    # Active sub: +1.5M
    db.add(Subscription(user_id=user.id, plan_id=plan.id, status="active"))
    db.commit()
    assert mrr_minor_units(db) >= 1_500_000


def test_signups_by_day_returns_recent_signups(db: Session):
    signup(db, email="jane@example.com", password="strongpass1")
    rows = signups_by_day(db, days=1)
    # At least the user we just created should show up.
    assert sum(count for _, count in rows) >= 1


def test_reports_by_model_groups_by_slug(db: Session):
    user = signup(db, email="kim@example.com", password="strongpass1")
    for slug in ("biotech", "biotech", "solar-farm"):
        db.add(
            ReportRun(
                user_id=user.id, model_slug=slug, format="xlsx",
                status="success", bytes_size=1234,
            )
        )
    db.commit()
    counts = reports_by_model(db, days=1)
    assert counts.get("biotech", 0) >= 2
    assert counts.get("solar-farm", 0) >= 1


def test_reports_by_model_filters_status(db: Session):
    user = signup(db, email="leo@example.com", password="strongpass1")
    db.add(
        ReportRun(
            user_id=user.id, model_slug="goat-farming", format="csv",
            status="failed", error_message="boom",
        )
    )
    db.commit()
    counts = reports_by_model(db, days=1, status="success")
    assert counts.get("goat-farming", 0) == 0
    failed_counts = reports_by_model(db, days=1, status="failed")
    assert failed_counts.get("goat-farming", 0) >= 1
