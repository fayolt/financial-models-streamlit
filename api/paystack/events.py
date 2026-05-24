"""Apply Paystack webhook events to our DB.

Each handler is idempotent — Paystack may retry the same event, and we
should never end up with duplicate Subscription rows. The two service
helpers (`activate_subscription`, `deactivate_subscription`) are also
called by the Streamlit "verify on callback" flow so both paths converge
on the same state transitions.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session as SASession

from app.db.models import Plan, Refund, Subscription, User


# --- Service helpers (also used outside webhook context) ---------------------


def activate_subscription(
    db: SASession,
    *,
    user: User,
    plan: Plan,
    subscription_code: str | None,
) -> Subscription:
    """Idempotently activate (or refresh) a subscription for a user.

    Lookup priority (so we never create a duplicate row when one webhook
    delivers without a code and a later one delivers with one, or vice
    versa):
      1. By paystack_subscription_code (if provided).
      2. By any existing active/past_due sub for this user — update it
         in place; if we also got a subscription_code now, backfill it.
      3. Create a new row.
    """
    sub: Subscription | None = None
    if subscription_code:
        sub = (
            db.query(Subscription)
            .filter_by(paystack_subscription_code=subscription_code)
            .first()
        )
    if sub is None:
        sub = (
            db.query(Subscription)
            .filter_by(user_id=user.id)
            .filter(Subscription.status.in_(("active", "past_due")))
            .order_by(Subscription.created_at.desc())
            .first()
        )

    if sub is None:
        sub = Subscription(
            user_id=user.id,
            plan_id=plan.id,
            status="active",
            paystack_subscription_code=subscription_code,
        )
        db.add(sub)
    else:
        sub.status = "active"
        sub.plan_id = plan.id
        sub.cancelled_at = None
        if subscription_code and not sub.paystack_subscription_code:
            sub.paystack_subscription_code = subscription_code

    user.tier = plan.tier
    db.commit()
    return sub


def deactivate_subscription(
    db: SASession,
    *,
    subscription_code: str | None = None,
    subscription_id: Any = None,
    demote_user: bool = True,
) -> Subscription | None:
    """Mark a subscription cancelled. Caller may identify it by Paystack code
    OR by primary-key UUID — useful when a sub was activated via the
    verify-transaction callback and never received a paystack_subscription_code."""
    sub: Subscription | None = None
    if subscription_code:
        sub = (
            db.query(Subscription)
            .filter_by(paystack_subscription_code=subscription_code)
            .first()
        )
    if sub is None and subscription_id is not None:
        sub = db.get(Subscription, subscription_id)
    if sub is None:
        return None
    sub.status = "cancelled"
    sub.cancelled_at = datetime.now(timezone.utc)
    if demote_user:
        user = db.get(User, sub.user_id)
        if user is not None:
            user.tier = "free"
    db.commit()
    return sub


# --- Internal helpers --------------------------------------------------------


def _user_from_customer(db: SASession, customer: dict[str, Any]) -> User | None:
    """Resolve a User from Paystack customer info (customer_code first, email fallback)."""
    customer_code = customer.get("customer_code")
    if customer_code:
        user = db.query(User).filter_by(paystack_customer_id=customer_code).first()
        if user is not None:
            return user
    email = (customer.get("email") or "").lower().strip()
    if email:
        user = db.query(User).filter_by(email=email).first()
        if user is not None and not user.paystack_customer_id and customer_code:
            user.paystack_customer_id = customer_code
        return user
    return None


# --- Webhook event handlers --------------------------------------------------


def handle_subscription_create(db: SASession, payload: dict[str, Any]) -> None:
    data = payload.get("data", {})
    user = _user_from_customer(db, data.get("customer", {}))
    if user is None:
        return

    plan_code = (data.get("plan") or {}).get("plan_code")
    if not plan_code:
        return
    plan = db.query(Plan).filter_by(paystack_plan_code=plan_code).first()
    if plan is None:
        return

    activate_subscription(
        db, user=user, plan=plan, subscription_code=data.get("subscription_code")
    )


def handle_subscription_disable(db: SASession, payload: dict[str, Any]) -> None:
    sub_code = (payload.get("data") or {}).get("subscription_code")
    if not sub_code:
        return
    deactivate_subscription(db, subscription_code=sub_code)


def handle_invoice_payment_failed(db: SASession, payload: dict[str, Any]) -> None:
    sub_code = (
        (payload.get("data") or {}).get("subscription") or {}
    ).get("subscription_code")
    if not sub_code:
        return
    sub = db.query(Subscription).filter_by(paystack_subscription_code=sub_code).first()
    if sub is None:
        return
    sub.status = "past_due"
    db.commit()


def _resolve_refund_row(db: SASession, data: dict[str, Any]) -> Refund | None:
    """Match a webhook payload to the Refund row we created on POST /refund.

    Look up by Paystack's refund id first; fall back to transaction reference
    if the row hasn't been backfilled yet (race between API response and
    webhook arrival).
    """
    refund_id = str(data.get("id") or "").strip()
    if refund_id:
        row = db.query(Refund).filter_by(paystack_refund_id=refund_id).first()
        if row is not None:
            return row
    tx_ref = (data.get("transaction") or {}).get("reference") or data.get("transaction_reference")
    if tx_ref:
        row = (
            db.query(Refund)
            .filter_by(paystack_transaction_reference=tx_ref, status="pending")
            .order_by(Refund.created_at.desc())
            .first()
        )
        if row is not None and refund_id and not row.paystack_refund_id:
            row.paystack_refund_id = refund_id
        return row
    return None


def handle_refund_processed(db: SASession, payload: dict[str, Any]) -> None:
    data = payload.get("data", {})
    row = _resolve_refund_row(db, data)
    if row is None:
        return
    row.status = "processed"
    row.processed_at = datetime.now(timezone.utc)
    db.commit()


def handle_refund_failed(db: SASession, payload: dict[str, Any]) -> None:
    data = payload.get("data", {})
    row = _resolve_refund_row(db, data)
    if row is None:
        return
    row.status = "failed"
    row.error_message = (data.get("reason") or data.get("status") or "")[:1000]
    row.processed_at = datetime.now(timezone.utc)
    db.commit()


def handle_invoice_payment_success(db: SASession, payload: dict[str, Any]) -> None:
    sub_code = (
        (payload.get("data") or {}).get("subscription") or {}
    ).get("subscription_code")
    if not sub_code:
        return
    sub = db.query(Subscription).filter_by(paystack_subscription_code=sub_code).first()
    if sub is None:
        return
    sub.status = "active"
    plan = db.get(Plan, sub.plan_id)
    user = db.get(User, sub.user_id)
    if plan is not None and user is not None:
        user.tier = plan.tier
    db.commit()


EVENT_HANDLERS: dict[str, Callable[[SASession, dict[str, Any]], None] | None] = {
    "subscription.create": handle_subscription_create,
    "subscription.disable": handle_subscription_disable,
    "invoice.payment_failed": handle_invoice_payment_failed,
    "invoice.update": handle_invoice_payment_success,
    "refund.processed": handle_refund_processed,
    "refund.failed": handle_refund_failed,
    "charge.success": None,
    "invoice.create": None,
}


def process_event(db: SASession, event: str, payload: dict[str, Any]) -> bool:
    """Return True if a handler ran, False if the event was unknown/ignored."""
    handler = EVENT_HANDLERS.get(event)
    if handler is None:
        return False
    handler(db, payload)
    return True
