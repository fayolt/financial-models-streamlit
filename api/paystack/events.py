"""Apply Paystack webhook events to our DB.

Each handler is idempotent — Paystack may retry the same event, and we
should never end up with duplicate Subscription rows.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session as SASession

from app.db.models import Plan, Subscription, User


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


def handle_subscription_create(db: SASession, payload: dict[str, Any]) -> None:
    data = payload.get("data", {})
    customer = data.get("customer", {})
    user = _user_from_customer(db, customer)
    if user is None:
        return

    plan_info = data.get("plan", {})
    plan_code = plan_info.get("plan_code")
    if not plan_code:
        return
    plan = db.query(Plan).filter_by(paystack_plan_code=plan_code).first()
    if plan is None:
        return

    sub_code = data.get("subscription_code")
    sub = (
        db.query(Subscription)
        .filter_by(paystack_subscription_code=sub_code)
        .first()
        if sub_code
        else None
    )
    if sub is None:
        sub = Subscription(
            user_id=user.id,
            plan_id=plan.id,
            status="active",
            paystack_subscription_code=sub_code,
        )
        db.add(sub)
    else:
        sub.status = "active"
        sub.plan_id = plan.id
        sub.cancelled_at = None

    user.tier = plan.tier
    db.commit()


def handle_subscription_disable(db: SASession, payload: dict[str, Any]) -> None:
    data = payload.get("data", {})
    sub_code = data.get("subscription_code")
    if not sub_code:
        return
    sub = db.query(Subscription).filter_by(paystack_subscription_code=sub_code).first()
    if sub is None:
        return
    sub.status = "cancelled"
    sub.cancelled_at = datetime.now(timezone.utc)

    user = db.get(User, sub.user_id)
    if user is not None:
        user.tier = "free"
    db.commit()


def handle_invoice_payment_failed(db: SASession, payload: dict[str, Any]) -> None:
    data = payload.get("data", {})
    sub_code = (data.get("subscription") or {}).get("subscription_code")
    if not sub_code:
        return
    sub = db.query(Subscription).filter_by(paystack_subscription_code=sub_code).first()
    if sub is None:
        return
    sub.status = "past_due"
    db.commit()


def handle_invoice_payment_success(db: SASession, payload: dict[str, Any]) -> None:
    """Renewal succeeded — make sure status is active."""
    data = payload.get("data", {})
    sub_code = (data.get("subscription") or {}).get("subscription_code")
    if not sub_code:
        return
    sub = db.query(Subscription).filter_by(paystack_subscription_code=sub_code).first()
    if sub is None:
        return
    sub.status = "active"

    # In case the user was demoted on a past_due, restore their tier from the plan.
    plan = db.get(Plan, sub.plan_id)
    user = db.get(User, sub.user_id)
    if plan and user:
        user.tier = plan.tier
    db.commit()


EVENT_HANDLERS: dict[str, Callable[[SASession, dict[str, Any]], None] | None] = {
    "subscription.create": handle_subscription_create,
    "subscription.disable": handle_subscription_disable,
    "invoice.payment_failed": handle_invoice_payment_failed,
    "invoice.update": handle_invoice_payment_success,  # Paystack fires this on renewal
    "charge.success": None,  # ignored: subscription.create covers initial activation
    "invoice.create": None,
}


def process_event(db: SASession, event: str, payload: dict[str, Any]) -> bool:
    """Return True if a handler ran, False if the event was unknown/ignored."""
    handler = EVENT_HANDLERS.get(event)
    if handler is None:
        return False
    handler(db, payload)
    return True
