"""Pricing page — shows tiers, opens Paystack checkout on Subscribe."""
from __future__ import annotations

import os

import streamlit as st

from api.paystack import PaystackError, initialize_transaction
from app.auth.gating import user_meets_tier
from app.db import SessionLocal
from app.db.models import Plan
from app.plugin.contract import SubscriptionTier


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

    if user_meets_tier(user["tier"], SubscriptionTier(plan.tier)):
        st.button(
            "Already on a higher tier",
            disabled=True,
            key=f"sub-{plan.slug}",
            use_container_width=True,
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
            f"Continue to Paystack →",
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

    if st.button(
        f"Subscribe to {plan.name}",
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
