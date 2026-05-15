"""Integration tests for the reports service: tier gating, quota, audit."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import engine
from app.db.models import Plan, ReportRun, User
from app.plugin import load_plugins
from app.plugin.contract import Format
from app.reports.service import (
    QuotaExceeded,
    TierTooLow,
    can_generate,
    generate_report_for_user,
    quota_remaining,
)


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


@pytest.fixture(scope="session")
def microbrewery_plugin():
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[1]
    return load_plugins(repo_root / "models").get("microbrewery")


def _make_user(db: Session, *, tier: str) -> User:
    user = User(
        email=f"reports_{uuid.uuid4().hex[:8]}@example.com",
        password_hash="$argon2id$placeholder",
        tier=tier,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _ensure_plans(db: Session) -> None:
    """Idempotently make sure the standard plans exist for quota lookups."""
    existing = {p.tier for p in db.query(Plan).all()}
    if "pro" not in existing:
        db.add(Plan(
            slug=f"pro-{uuid.uuid4().hex[:6]}", name="Pro",
            tier="pro", monthly_price_minor_units=1_500_000,
            currency="NGN", monthly_report_quota=50,
        ))
    if "enterprise" not in existing:
        db.add(Plan(
            slug=f"enterprise-{uuid.uuid4().hex[:6]}", name="Enterprise",
            tier="enterprise", monthly_price_minor_units=5_000_000,
            currency="NGN", monthly_report_quota=None,
        ))
    db.commit()


# --- can_generate ------------------------------------------------------------


def test_can_generate_free_user_blocked_from_all():
    for fmt in (Format.XLSX, Format.CSV, Format.PDF, Format.DOCX):
        assert not can_generate(user_tier="free", fmt=fmt)


def test_can_generate_pro_user_gets_xlsx_csv_only():
    assert can_generate(user_tier="pro", fmt=Format.XLSX)
    assert can_generate(user_tier="pro", fmt=Format.CSV)
    assert not can_generate(user_tier="pro", fmt=Format.PDF)
    assert not can_generate(user_tier="pro", fmt=Format.DOCX)


def test_can_generate_enterprise_unlocks_everything():
    for fmt in (Format.XLSX, Format.CSV, Format.PDF, Format.DOCX):
        assert can_generate(user_tier="enterprise", fmt=fmt)


# --- quota_remaining ---------------------------------------------------------


def test_quota_free_user_is_zero(db: Session):
    user = _make_user(db, tier="free")
    assert quota_remaining(db, user.id) == 0


def test_quota_enterprise_is_unlimited(db: Session):
    _ensure_plans(db)
    user = _make_user(db, tier="enterprise")
    assert quota_remaining(db, user.id) is None


def test_quota_pro_is_plan_limit(db: Session):
    _ensure_plans(db)
    user = _make_user(db, tier="pro")
    plan = db.query(Plan).filter_by(tier="pro").first()
    assert quota_remaining(db, user.id) == plan.monthly_report_quota


def test_quota_decrements_on_success(db: Session):
    _ensure_plans(db)
    user = _make_user(db, tier="pro")
    initial = quota_remaining(db, user.id)
    db.add(ReportRun(
        user_id=user.id, model_slug="x", format="xlsx",
        status="success", started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    ))
    db.commit()
    assert quota_remaining(db, user.id) == initial - 1


def test_quota_ignores_failed_runs(db: Session):
    _ensure_plans(db)
    user = _make_user(db, tier="pro")
    initial = quota_remaining(db, user.id)
    db.add(ReportRun(
        user_id=user.id, model_slug="x", format="xlsx",
        status="failed", error_message="boom",
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    ))
    db.commit()
    assert quota_remaining(db, user.id) == initial


# --- generate_report_for_user ------------------------------------------------


def test_generate_report_free_user_blocked(db: Session, microbrewery_plugin):
    _ensure_plans(db)
    user = _make_user(db, tier="free")
    inputs = microbrewery_plugin.default_inputs()
    results = microbrewery_plugin.compute(inputs)
    with pytest.raises(TierTooLow):
        generate_report_for_user(
            db,
            plugin=microbrewery_plugin,
            inputs=inputs,
            results=results,
            fmt=Format.XLSX,
            user_id=user.id,
        )


def test_generate_report_pro_user_succeeds(db: Session, microbrewery_plugin):
    _ensure_plans(db)
    user = _make_user(db, tier="pro")
    inputs = microbrewery_plugin.default_inputs()
    results = microbrewery_plugin.compute(inputs)
    data = generate_report_for_user(
        db,
        plugin=microbrewery_plugin,
        inputs=inputs,
        results=results,
        fmt=Format.XLSX,
        user_id=user.id,
    )
    assert isinstance(data, bytes) and len(data) > 0

    runs = db.query(ReportRun).filter_by(user_id=user.id, status="success").all()
    assert len(runs) == 1
    assert runs[0].model_slug == "microbrewery"
    assert runs[0].format == "xlsx"
    assert runs[0].bytes_size == len(data)
    assert runs[0].completed_at is not None


def test_generate_report_pro_user_blocked_from_pdf(db: Session, microbrewery_plugin):
    _ensure_plans(db)
    user = _make_user(db, tier="pro")
    inputs = microbrewery_plugin.default_inputs()
    results = microbrewery_plugin.compute(inputs)
    with pytest.raises(TierTooLow, match="Enterprise"):
        generate_report_for_user(
            db,
            plugin=microbrewery_plugin,
            inputs=inputs,
            results=results,
            fmt=Format.PDF,
            user_id=user.id,
        )


def test_generate_report_quota_exhausted(db: Session, microbrewery_plugin):
    _ensure_plans(db)
    user = _make_user(db, tier="pro")
    pro_plan = db.query(Plan).filter_by(tier="pro").first()
    # Pre-fill report_runs to push quota_remaining to 0.
    for _ in range(pro_plan.monthly_report_quota):
        db.add(ReportRun(
            user_id=user.id, model_slug="x", format="xlsx",
            status="success",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        ))
    db.commit()

    inputs = microbrewery_plugin.default_inputs()
    results = microbrewery_plugin.compute(inputs)
    with pytest.raises(QuotaExceeded):
        generate_report_for_user(
            db,
            plugin=microbrewery_plugin,
            inputs=inputs,
            results=results,
            fmt=Format.XLSX,
            user_id=user.id,
        )
