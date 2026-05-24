"""Admin/support operations: user search, detail view, manual tier adjust."""
from __future__ import annotations

from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import desc
from sqlalchemy.orm import Session as SASession

from api.paystack import PaystackError, issue_refund as paystack_issue_refund
from app.db.models import (
    AdminAuditLog,
    Plan,
    Refund,
    ReportRun,
    Subscription,
    User,
)


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
    refunds = (
        db.query(Refund)
        .filter_by(user_id=user_id)
        .order_by(desc(Refund.created_at))
        .limit(25)
        .all()
    )
    return {
        "user": user,
        "subscriptions": subs,
        "recent_runs": recent_runs,
        "refunds": refunds,
    }


def _record_audit(
    db: SASession,
    *,
    actor_id: UUID,
    action: str,
    target_user_id: UUID | None = None,
    payload: dict | None = None,
) -> AdminAuditLog:
    entry = AdminAuditLog(
        actor_id=actor_id,
        action=action,
        target_user_id=target_user_id,
        payload=payload,
    )
    db.add(entry)
    db.commit()
    return entry


def set_user_tier(
    db: SASession,
    user_id: UUID,
    new_tier: str,
    *,
    actor_id: UUID | None = None,
) -> User:
    if new_tier not in _VALID_TIERS:
        raise ValueError(
            f"Invalid tier {new_tier!r}; expected one of {_VALID_TIERS}"
        )
    user = db.get(User, user_id)
    if user is None:
        raise ValueError(f"User {user_id} not found")
    previous = user.tier
    user.tier = new_tier
    db.commit()
    db.refresh(user)
    if actor_id is not None and previous != new_tier:
        _record_audit(
            db,
            actor_id=actor_id,
            action="set_tier",
            target_user_id=user_id,
            payload={"from": previous, "to": new_tier},
        )
    return user


def set_user_admin(
    db: SASession,
    user_id: UUID,
    is_admin: bool,
    *,
    actor_id: UUID,
) -> User:
    """Grant or revoke admin. Audited. Refuses self-demotion to avoid lockout."""
    if is_admin is False and actor_id == user_id:
        raise ValueError(
            "Admins cannot demote themselves — ask another admin or use the CLI."
        )
    user = db.get(User, user_id)
    if user is None:
        raise ValueError(f"User {user_id} not found")
    if user.is_admin == is_admin:
        return user
    user.is_admin = is_admin
    db.commit()
    db.refresh(user)
    _record_audit(
        db,
        actor_id=actor_id,
        action="set_admin" if is_admin else "unset_admin",
        target_user_id=user_id,
        payload={"is_admin": is_admin, "email": user.email},
    )
    return user


def issue_refund_for_user(
    db: SASession,
    *,
    user_id: UUID | None,
    transaction_reference: str,
    reason: str,
    amount_minor_units: int | None,
    currency: str,
    actor_id: UUID,
) -> Refund:
    """Issue a refund via Paystack and record it locally.

    Order of operations:
    1. Call Paystack POST /refund. If that fails, raise — no DB row created.
    2. Insert Refund row with status='pending' and the returned refund id.
    3. Audit log the action.
    4. The refund.processed / refund.failed webhook later flips the status.
    """
    transaction_reference = transaction_reference.strip()
    if not transaction_reference:
        raise ValueError("Transaction reference is required.")
    reason = reason.strip()
    if not reason:
        raise ValueError("A reason is required for compliance.")
    if amount_minor_units is not None and amount_minor_units <= 0:
        raise ValueError("Amount must be positive (or omit it for a full refund).")

    try:
        result = paystack_issue_refund(
            transaction_reference=transaction_reference,
            amount_minor_units=amount_minor_units,
            currency=currency,
            merchant_note=reason[:200],
        )
    except PaystackError as exc:
        raise RuntimeError(f"Paystack refund failed: {exc}") from exc

    paystack_refund_id = str(result.get("id") or "").strip() or None

    refund = Refund(
        user_id=user_id,
        created_by_admin_id=actor_id,
        paystack_transaction_reference=transaction_reference,
        paystack_refund_id=paystack_refund_id,
        amount_minor_units=amount_minor_units,
        currency=currency,
        reason=reason,
        status="pending",
    )
    db.add(refund)
    db.commit()
    db.refresh(refund)

    _record_audit(
        db,
        actor_id=actor_id,
        action="issue_refund",
        target_user_id=user_id,
        payload={
            "transaction_reference": transaction_reference,
            "amount_minor_units": amount_minor_units,
            "currency": currency,
            "reason": reason,
            "paystack_refund_id": paystack_refund_id,
        },
    )
    return refund


def recent_audit_entries_for_user(
    db: SASession, target_user_id: UUID, limit: int = 25
) -> list[AdminAuditLog]:
    return (
        db.query(AdminAuditLog)
        .filter_by(target_user_id=target_user_id)
        .order_by(desc(AdminAuditLog.created_at))
        .limit(limit)
        .all()
    )
