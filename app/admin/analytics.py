"""Business-analytics queries for the admin dashboard.

Read-only aggregates over the existing tables — no new schema. All
timestamps are interpreted in UTC.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session as SASession

from app.db.models import Plan, ReportRun, Subscription, User


def total_active_users(db: SASession) -> int:
    return (
        db.query(func.count(User.id))
        .filter(User.is_active.is_(True))
        .scalar()
        or 0
    )


def tier_distribution(db: SASession) -> dict[str, int]:
    rows = (
        db.query(User.tier, func.count(User.id))
        .filter(User.is_active.is_(True))
        .group_by(User.tier)
        .all()
    )
    return {tier: count for tier, count in rows}


def mrr_minor_units(db: SASession) -> int:
    """Sum of monthly_price_minor_units across active subscriptions.

    NOTE: assumes a single currency. Multi-currency support would split
    this by `plans.currency` and surface each separately."""
    total = (
        db.query(func.coalesce(func.sum(Plan.monthly_price_minor_units), 0))
        .select_from(Subscription)
        .join(Plan, Subscription.plan_id == Plan.id)
        .filter(Subscription.status == "active")
        .scalar()
    )
    return int(total or 0)


def signups_by_day(db: SASession, days: int = 30) -> list[tuple[date, int]]:
    """List of (day, count) ordered by day ascending, last `days` days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        db.query(
            func.date(User.created_at).label("day"),
            func.count(User.id).label("count"),
        )
        .filter(User.created_at >= cutoff)
        .group_by("day")
        .order_by("day")
        .all()
    )
    return [(r.day, int(r.count)) for r in rows]


def reports_by_model(
    db: SASession, days: int = 30, status: str = "success"
) -> dict[str, int]:
    """Successful (by default) report runs per model_slug, last `days` days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        db.query(ReportRun.model_slug, func.count(ReportRun.id))
        .filter(ReportRun.started_at >= cutoff, ReportRun.status == status)
        .group_by(ReportRun.model_slug)
        .order_by(func.count(ReportRun.id).desc())
        .all()
    )
    return {slug: int(count) for slug, count in rows}
