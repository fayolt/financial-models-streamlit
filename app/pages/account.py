"""Account page: profile, current subscription, Paystack callback handling, logout."""
from __future__ import annotations

from uuid import UUID

import streamlit as st

from api.paystack import (
    PaystackError,
    activate_subscription,
    deactivate_subscription,
    disable_subscription,
    verify_transaction,
)
from app.auth.cookie import clear_session_token
from app.auth.service import logout
from app.db import SessionLocal
from app.db.models import Plan, Subscription, User


def _handle_paystack_callback() -> None:
    """If the URL has ?reference=..., verify it with Paystack and activate the sub."""
    qp = st.query_params
    reference = qp.get("reference") or qp.get("trxref")
    if not reference:
        return
    # Only verify once per reference (refreshes shouldn't re-verify).
    verified_key = f"verified_ref_{reference}"
    if st.session_state.get(verified_key):
        st.query_params.clear()
        return

    with st.spinner("Verifying your payment with Paystack…"):
        try:
            data = verify_transaction(reference)
        except PaystackError as e:
            st.error(f"Could not verify payment: {e}")
            st.session_state[verified_key] = True
            return

    if data.get("status") != "success":
        st.warning(f"Payment status: {data.get('status', 'unknown')}.")
        st.session_state[verified_key] = True
        return

    # Sync local DB so the user sees the upgrade immediately even if the
    # subscription.create webhook hasn't arrived yet (it's idempotent).
    customer_email = (data.get("customer") or {}).get("email", "").lower()
    plan_info = data.get("plan_object") or data.get("plan") or {}
    plan_code = plan_info.get("plan_code") if isinstance(plan_info, dict) else None
    subscription_code = None
    # Paystack puts the subscription on `subscription` for recurring transactions.
    sub_obj = data.get("subscription") or {}
    if isinstance(sub_obj, dict):
        subscription_code = sub_obj.get("subscription_code")

    if plan_code:
        with SessionLocal() as db:
            user_row = (
                db.query(User).filter_by(email=customer_email).first()
                if customer_email
                else db.get(User, UUID(st.session_state.user["id"]))
            )
            plan = db.query(Plan).filter_by(paystack_plan_code=plan_code).first()
            if user_row is not None and plan is not None:
                activate_subscription(
                    db, user=user_row, plan=plan, subscription_code=subscription_code
                )
                # Refresh the session-state cache of user info.
                st.session_state.user["tier"] = user_row.tier

    amount = (data.get("amount") or 0) / 100
    currency = data.get("currency", "")
    st.success(
        f"Payment of {currency} {amount:,.2f} confirmed. Your plan is now active."
    )
    st.session_state[verified_key] = True
    st.query_params.clear()


def _render_subscription_block(user_id: UUID) -> None:
    with SessionLocal() as db:
        sub = (
            db.query(Subscription)
            .filter_by(user_id=user_id)
            .filter(Subscription.status.in_(("active", "past_due")))
            .order_by(Subscription.created_at.desc())
            .first()
        )
        if sub is None:
            st.info("No active subscription. Visit the Pricing page to upgrade.")
            return
        plan = db.get(Plan, sub.plan_id)

    st.subheader("Active subscription")
    st.markdown(f"**Plan:** {plan.name}  ·  {plan.currency} {plan.monthly_price_minor_units / 100:,.0f}/mo")
    badge = {"active": "🟢 Active", "past_due": "🟡 Past due"}.get(sub.status, sub.status)
    st.markdown(f"**Status:** {badge}")

    cancel_key = f"confirming_cancel_{sub.id}"
    if st.session_state.get(cancel_key):
        st.warning("Cancel this subscription? You'll be demoted to the Free tier at the end of the current period.")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Yes, cancel", type="primary", use_container_width=True):
                if sub.paystack_subscription_code:
                    try:
                        disable_subscription(sub.paystack_subscription_code)
                    except PaystackError as e:
                        st.error(f"Paystack error: {e}")
                        return
                with SessionLocal() as db:
                    if sub.paystack_subscription_code:
                        deactivate_subscription(
                            db, subscription_code=sub.paystack_subscription_code
                        )
                    user = db.get(User, user_id)
                    if user is not None:
                        st.session_state.user["tier"] = user.tier
                st.session_state.pop(cancel_key, None)
                st.success("Subscription cancelled.")
                st.rerun()
        with c2:
            if st.button("Keep my plan", use_container_width=True):
                st.session_state.pop(cancel_key, None)
                st.rerun()
    else:
        if st.button("Cancel subscription"):
            st.session_state[cancel_key] = True
            st.rerun()


def render() -> None:
    user = st.session_state.get("user")
    if user is None:
        st.error("Not logged in.")
        return

    _handle_paystack_callback()

    st.title("Account")
    st.markdown(f"**Email:** {user['email']}")
    if user.get("full_name"):
        st.markdown(f"**Name:** {user['full_name']}")
    st.markdown(f"**Subscription tier:** {user['tier'].title()}")

    st.divider()
    _render_subscription_block(UUID(user["id"]))

    st.divider()
    if st.button("Log out", type="primary"):
        token = st.session_state.get("session_token")
        if token:
            with SessionLocal() as db:
                logout(db, token)
        clear_session_token()
        st.session_state.pop("user", None)
        st.session_state.pop("session_token", None)
        st.rerun()
