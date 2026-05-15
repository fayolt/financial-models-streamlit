"""Admin/support operations: user search, detail view, manual tier adjust."""
from __future__ import annotations

from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import desc
from sqlalchemy.orm import Session as SASession

from app.db.models import Plan, ReportRun, Subscription, User


class NotAdminError(PermissionError):
    """Raised when a non-admin tries to use an admin operation."""


_VALID_TIERS = ("free", "pro", "enterprise")


def require_admin(user: Mapping[str, Any] | None) -> None:
    """Raise NotAdminError if the user dict in session_state isn't an admin."""
    if not user or not user.get("is_admin"):
        raise NotAdminError("Admin access required.")


def list_users(
    db: SASession,
    *,
    search: str | None = None,
    limit: int = 100,
) -> list[User]:
    q = db.query(User)
    if search:
        q = q.filter(User.email.ilike(f"%{search.strip()}%"))
    return q.order_by(User.created_at.desc()).limit(limit).all()


def get_user_detail(db: SASession, user_id: UUID) -> dict | None:
    user = db.get(User, user_id)
    if user is None:
        return None
    subs = (
        db.query(Subscription, Plan)
        .outerjoin(Plan, Subscription.plan_id == Plan.id)
        .filter(Subscription.user_id == user_id)
        .order_by(desc(Subscription.created_at))
        .all()
    )
    recent_runs = (
        db.query(ReportRun)
        .filter_by(user_id=user_id)
        .order_by(desc(ReportRun.started_at))
        .limit(25)
        .all()
    )
    return {"user": user, "subscriptions": subs, "recent_runs": recent_runs}


def set_user_tier(db: SASession, user_id: UUID, new_tier: str) -> User:
    if new_tier not in _VALID_TIERS:
        raise ValueError(
            f"Invalid tier {new_tier!r}; expected one of {_VALID_TIERS}"
        )
    user = db.get(User, user_id)
    if user is None:
        raise ValueError(f"User {user_id} not found")
    user.tier = new_tier
    db.commit()
    db.refresh(user)
    return user
