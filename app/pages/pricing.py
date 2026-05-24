"""Pricing page — shows tiers, opens Paystack checkout on Subscribe.

Upgrade flow (Pro → Enterprise) cancels the current Paystack subscription
first, then opens checkout for the higher tier. Paystack auto-prorates
the unused time. Downgrades are intentionally not exposed here —
the user cancels and re-subscribes when ready.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from uuid import UUID

import streamlit as st

from api.paystack import (
    PaystackError,
    deactivate_subscription,
    disable_subscription,
    initialize_transaction,
)
from app.auth.gating import user_meets_tier
from app.db import SessionLocal
from app.db.models import Plan, Subscription
from app.plugin.contract import SubscriptionTier

_log = logging.getLogger("app.pricing")

_TIER_RANK = {"free": 0, "pro": 1, "enterprise": 2}


_FEATURES_BY_TIER: dict[str, list[str]] = {
    "free": [
        "View all 7 financial models on-screen",
        "No exports",
    ],
    "pro": [
        "Everything in Free",
        "XLSX exports for every model",
        "50 reports per month",
    ],
    "enterprise": [
        "Everything in Pro",
        "PDF + DOCX exports",
        "Unlimited reports",
        "AI-generated commentary (biotech, chicken-farming)",
    ],
}


def _format_price(plan: Plan) -> str:
    if plan.monthly_price_minor_units == 0:
        return "Free"
    return f"{plan.currency} {plan.monthly_price_minor_units / 100:,.0f}/mo"


def _start_checkout(plan: Plan, user_email: str) -> str:
    """Initialise a Paystack transaction; return the authorization URL."""
    callback_url = os.environ.get(
        "PAYSTACK_CALLBACK_URL", "http://localhost:8501/account"
    )
    metadata = {"plan_slug": plan.slug, "plan_id": str(plan.id)}
    result = initialize_transaction(
        email=user_email,
        amount_kobo=plan.monthly_price_minor_units,
        plan_code=plan.paystack_plan_code,
        callback_url=callback_url,
        metadata=metadata,
    )
    return result["authorization_url"]


def _render_plan_card(plan: Plan, user: dict, *, email_verified: bool = True) -> None:
    is_current = user["tier"] == plan.tier
    current_rank = _TIER_RANK.get(user["tier"], 0)
    target_rank = _TIER_RANK.get(plan.tier, 0)
    is_upgrade = target_rank > current_rank
    is_downgrade = target_rank < current_rank and plan.tier != "free"

    st.subheader(plan.name)
    st.caption(_format_price(plan))
    for feature in _FEATURES_BY_TIER.get(plan.tier, []):
        st.markdown(f"- {feature}")
    st.write("")

    if plan.tier == "free":
        label = "Current plan" if is_current else "Default tier"
        st.button(label, disabled=True, key=f"sub-{plan.slug}", use_container_width=True)
        return

    if is_current:
        st.success("Current plan")
        return

    if is_downgrade:
        st.button(
            f"Downgrade to {plan.name}",
            disabled=True,
            key=f"sub-{plan.slug}",
            use_container_width=True,
            help="To downgrade, cancel your current plan from the Account page; "
                 "you'll keep access until the period ends, then can subscribe to a lower tier.",
        )
        return

    if not plan.paystack_plan_code:
        st.warning("Paystack plan not configured")
        st.caption("Run `make paystack-sync`.")
        return

    checkout_key = f"checkout_url_{plan.slug}"
    if checkout_key in st.session_state:
        url = st.session_state[checkout_key]
        st.link_button(
            "Continue to Paystack →",
            url,
            type="primary",
            use_container_width=True,
        )
        if st.button(
            "Cancel",
            key=f"cancel-{plan.slug}",
            use_container_width=True,
        ):
            st.session_state.pop(checkout_key, None)
            st.rerun()
        return

    # Upgrade flow requires extra confirmation because we cancel the
    # current paid sub before opening checkout for the new tier.
    if is_upgrade and current_rank > 0:
        _render_upgrade_button(plan, user, email_verified, checkout_key)
        return

    button_label = f"Subscribe to {plan.name}"
    if st.button(
        button_label,
        type="primary",
        key=f"sub-{plan.slug}",
        use_container_width=True,
        disabled=not email_verified,
        help=None if email_verified else "Verify your email before subscribing.",
    ):
        try:
            url = _start_checkout(plan, user["email"])
        except PaystackError as e:
            st.error(f"Paystack error: {e}")
            return
        except Exception as e:  # pragma: no cover — network / unexpected
            st.error(f"Could not start checkout: {e}")
            return
        st.session_state[checkout_key] = url
        st.rerun()


def _render_upgrade_button(
    plan: Plan, user: dict, email_verified: bool, checkout_key: str
) -> None:
    """Two-step upgrade: confirmation → cancel current sub → open new checkout."""
    confirm_key = f"upgrade_confirm_{plan.slug}"
    if st.session_state.get(confirm_key):
        st.warning(
            f"Upgrade to **{plan.name}**? Your current {user['tier'].title()} "
            "subscription will be cancelled and a new checkout will open. "
            "Paystack will credit your unused time toward the new plan."
        )
        c1, c2 = st.columns(2)
        with c1:
            if st.button(
                "Confirm upgrade",
                type="primary",
                key=f"upgrade-yes-{plan.slug}",
                use_container_width=True,
                disabled=not email_verified,
                help=None if email_verified else "Verify your email before upgrading.",
            ):
                try:
                    _cancel_current_paid_subscription(UUID(user["id"]))
                    url = _start_checkout(plan, user["email"])
                except PaystackError as e:
                    st.error(f"Paystack error: {e}")
                    return
                except Exception as e:
                    st.error(f"Upgrade failed: {e}")
                    return
                st.session_state.pop(confirm_key, None)
                st.session_state[checkout_key] = url
                st.rerun()
        with c2:
            if st.button(
                "Cancel",
                key=f"upgrade-no-{plan.slug}",
                use_container_width=True,
            ):
                st.session_state.pop(confirm_key, None)
                st.rerun()
        return

    if st.button(
        f"Upgrade to {plan.name}",
        type="primary",
        key=f"sub-{plan.slug}",
        use_container_width=True,
        disabled=not email_verified,
        help=None if email_verified else "Verify your email before upgrading.",
    ):
        st.session_state[confirm_key] = True
        st.rerun()


def _cancel_current_paid_subscription(user_id: UUID) -> None:
    """Cancel the user's active/past_due subscription on Paystack and locally.

    Tolerates already-cancelled subs and missing paystack codes (logs a
    warning but does not raise — we want the upgrade to proceed).
    """
    with SessionLocal() as db:
        sub = (
            db.query(Subscription)
            .filter_by(user_id=user_id)
            .filter(Subscription.status.in_(("active", "past_due")))
            .order_by(Subscription.created_at.desc())
            .first()
        )
        if sub is None:
            return  # nothing to cancel; user must already be on free

        sub_code = sub.paystack_subscription_code
        sub_id = sub.id

    if sub_code:
        try:
            disable_subscription(sub_code)
        except PaystackError as exc:
            # Don't block the upgrade — Paystack may already have it disabled
            # or may flag it on the next renewal. We surface the warning later.
            _log.warning(
                "could not disable existing sub %s during upgrade: %s",
                sub_code, exc,
            )

    with SessionLocal() as db:
        deactivate_subscription(
            db,
            subscription_code=sub_code,
            subscription_id=sub_id,
            demote_user=False,  # tier will be set when the new sub activates
        )


def render() -> None:
    user = st.session_state.get("user")
    if user is None:
        st.error("Please log in first.")
        return

    st.title("Pricing")
    st.write(
        "Pick the plan that fits how you use the financial models. "
        "Billing is monthly in ZAR; cancel anytime from your Account."
    )
    st.divider()

    with SessionLocal() as db:
        from app.db.models import User
        db_user = db.get(User, user["id"])
        email_verified = bool(db_user and db_user.email_verified_at)

        plans = (
            db.query(Plan)
            .filter_by(is_active=True)
            .order_by(Plan.monthly_price_minor_units)
            .all()
        )

    if not plans:
        st.warning("No plans configured. Run `make seed`.")
        return

    if not email_verified:
        st.warning(
            "Please verify your email before subscribing to a paid plan. "
            "Check the inbox for **{email}** — we sent a confirmation link "
            "when you signed up.".format(email=user["email"])
        )
        if st.button("Resend verification email", key="resend-verify"):
            from app.auth.service import request_email_verification
            from uuid import UUID
            with SessionLocal() as db:
                sent = request_email_verification(db, user_id=UUID(user["id"]))
            if sent:
                st.success("Verification email re-sent.")
            else:
                st.info("Your email is already verified — refresh the page.")
        st.divider()

    cols = st.columns(len(plans))
    for col, plan in zip(cols, plans):
        with col:
            _render_plan_card(plan, user, email_verified=email_verified)
