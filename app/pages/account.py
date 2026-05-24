"""Account page: profile, security, subscription, Paystack callback, danger zone."""
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
from app.auth.service import (
    AuthError,
    change_password,
    delete_account,
    logout,
    update_profile,
)
from app.db import SessionLocal
from app.db.models import Plan, Subscription, User


# --- Paystack callback (unchanged from prior phase) -------------------------


def _handle_paystack_callback() -> None:
    qp = st.query_params
    reference = qp.get("reference") or qp.get("trxref")
    if not reference:
        return
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

    customer_email = (data.get("customer") or {}).get("email", "").lower()
    plan_info = data.get("plan_object") or data.get("plan") or {}
    plan_code = plan_info.get("plan_code") if isinstance(plan_info, dict) else None
    sub_obj = data.get("subscription") or {}
    subscription_code = (
        sub_obj.get("subscription_code") if isinstance(sub_obj, dict) else None
    )

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
                st.session_state.user["tier"] = user_row.tier

    amount = (data.get("amount") or 0) / 100
    currency = data.get("currency", "")
    st.success(
        f"Payment of {currency} {amount:,.2f} confirmed. Your plan is now active."
    )
    st.session_state[verified_key] = True
    st.query_params.clear()


# --- Section: profile + security --------------------------------------------


def _render_profile_section(user_id: UUID) -> None:
    user_dict = st.session_state.user
    st.subheader("Profile")
    with st.form("profile_form"):
        full_name = st.text_input("Full name", value=user_dict.get("full_name") or "")
        submitted = st.form_submit_button("Save")
    if submitted:
        with SessionLocal() as db:
            try:
                user = update_profile(db, user_id=user_id, full_name=full_name)
            except AuthError as e:
                st.error(str(e))
                return
        st.session_state.user["full_name"] = user.full_name
        st.success("Profile updated.")


def _render_security_section(user_id: UUID) -> None:
    st.subheader("Security")
    with st.expander("Change password"):
        with st.form("change_password_form", clear_on_submit=True):
            current = st.text_input("Current password", type="password")
            new = st.text_input("New password", type="password", help="At least 8 characters.")
            confirm = st.text_input("Confirm new password", type="password")
            submitted = st.form_submit_button("Update password", type="primary")
        if not submitted:
            return
        if not current or not new:
            st.error("All fields are required.")
            return
        if new != confirm:
            st.error("New passwords do not match.")
            return
        keep_token = st.session_state.get("session_token")
        with SessionLocal() as db:
            try:
                change_password(
                    db,
                    user_id=user_id,
                    current_password=current,
                    new_password=new,
                    keep_current_session_token=keep_token,
                )
            except AuthError as e:
                st.error(str(e))
                return
        st.success("Password updated. Other devices have been signed out.")


# --- Section: subscription (unchanged) --------------------------------------


def _render_no_subscription_cta() -> None:
    """Inline pricing preview shown when the user has no active subscription."""
    st.info("You are on the **Free** plan — upgrade to unlock exports and AI commentary.")
    st.write("")

    cols = st.columns(3)
    _PLANS = [
        {
            "name": "Free",
            "price": "ZAR 0/mo",
            "features": ["View all 7 models", "On-screen only", "No exports"],
            "highlight": False,
        },
        {
            "name": "Pro",
            "price": "ZAR 250/mo",
            "features": ["Everything in Free", "XLSX exports", "50 reports/mo"],
            "highlight": True,
        },
        {
            "name": "Enterprise",
            "price": "ZAR 300/mo",
            "features": ["Everything in Pro", "PDF + DOCX exports", "AI commentary · Unlimited"],
            "highlight": False,
        },
    ]

    for col, plan in zip(cols, _PLANS):
        with col:
            border_style = (
                "border:2px solid #16a34a;border-radius:0.5rem;padding:0.75rem;"
                if plan["highlight"]
                else "border:1px solid #e2e8f0;border-radius:0.5rem;padding:0.75rem;"
            )
            features_html = "".join(
                f"<li style='font-size:0.8rem;color:#475569;'>{f}</li>"
                for f in plan["features"]
            )
            st.markdown(
                f"<div style='{border_style}'>"
                f"<div style='font-weight:700;font-size:0.95rem;'>{plan['name']}</div>"
                f"<div style='color:#16a34a;font-size:0.85rem;margin:0.2rem 0 0.5rem;'>{plan['price']}</div>"
                f"<ul style='margin:0;padding-left:1rem;'>{features_html}</ul>"
                f"</div>",
                unsafe_allow_html=True,
            )

    st.write("")
    st.link_button("See full pricing & subscribe →", url="/pricing", type="primary")


def _render_subscription_block(user_id: UUID) -> None:
    st.subheader("Subscription")
    with SessionLocal() as db:
        sub = (
            db.query(Subscription)
            .filter_by(user_id=user_id)
            .filter(Subscription.status.in_(("active", "past_due")))
            .order_by(Subscription.created_at.desc())
            .first()
        )
        if sub is None:
            _render_no_subscription_cta()
            return
        plan = db.get(Plan, sub.plan_id)
    st.markdown(
        f"**Plan:** {plan.name}  ·  {plan.currency} {plan.monthly_price_minor_units / 100:,.0f}/mo"
    )
    badge = {"active": "🟢 Active", "past_due": "🟡 Past due"}.get(sub.status, sub.status)
    st.markdown(f"**Status:** {badge}")

    cancel_key = f"confirming_cancel_{sub.id}"
    if st.session_state.get(cancel_key):
        st.warning(
            "Cancel this subscription? You'll be demoted to the Free tier at the "
            "end of the current period."
        )
        c1, c2 = st.columns(2)
        with c1:
            if st.button(
                "Yes, cancel",
                type="primary",
                use_container_width=True,
                key=f"confirm-cancel-{sub.id}",
            ):
                # If we never received a paystack_subscription_code (webhook
                # missed or delayed), refuse to cancel locally — otherwise the
                # user sees "cancelled" in our UI but Paystack keeps charging.
                if not sub.paystack_subscription_code:
                    st.error(
                        "We couldn't sync this subscription with Paystack yet, "
                        "so cancelling here would not stop billing. Please "
                        "contact support@numquants.com — we'll cancel it on "
                        "the Paystack side and refund any charges since you "
                        "requested cancellation."
                    )
                    st.session_state.pop(cancel_key, None)
                    return
                try:
                    disable_subscription(sub.paystack_subscription_code)
                except Exception as e:
                    st.warning(
                        f"Paystack call failed (`{e}`). Cancelling locally "
                        "anyway — you may also need to cancel on the "
                        "Paystack side to fully stop billing."
                    )
                # Cancel ALL active/past_due subs for this user — they may have
                # accumulated duplicates from re-delivered webhooks or repeated
                # verify-transaction callbacks.
                from datetime import datetime, timezone

                with SessionLocal() as db:
                    now = datetime.now(timezone.utc)
                    open_subs = (
                        db.query(Subscription)
                        .filter_by(user_id=user_id)
                        .filter(Subscription.status.in_(("active", "past_due")))
                        .all()
                    )
                    for open_sub in open_subs:
                        open_sub.status = "cancelled"
                        open_sub.cancelled_at = now
                    refreshed = db.get(User, user_id)
                    if refreshed is not None:
                        refreshed.tier = "free"
                        st.session_state.user["tier"] = "free"
                    db.commit()
                st.session_state.pop(cancel_key, None)
                st.success("Subscription cancelled.")
                st.rerun()
        with c2:
            if st.button(
                "Keep my plan",
                use_container_width=True,
                key=f"keep-plan-{sub.id}",
            ):
                st.session_state.pop(cancel_key, None)
                st.rerun()
    else:
        if st.button("Cancel subscription", key=f"cancel-btn-{sub.id}"):
            st.session_state[cancel_key] = True
            st.rerun()


# --- Section: danger zone ---------------------------------------------------


def _render_danger_zone(user_id: UUID) -> None:
    st.subheader("Danger zone")
    with st.expander("Delete account"):
        st.warning(
            "Deleting your account permanently removes your profile, subscriptions, "
            "report history, and saved scenarios. Any active subscription is cancelled. "
            "**This cannot be undone.**"
        )
        with st.form("delete_account_form"):
            confirm_pw = st.text_input("Confirm with your password", type="password")
            confirm_check = st.checkbox(
                "I understand my data will be permanently deleted."
            )
            submitted = st.form_submit_button("Delete my account", type="primary")
        if not submitted:
            return
        if not confirm_check:
            st.error("You must confirm before deletion.")
            return
        if not confirm_pw:
            st.error("Password is required.")
            return
        with SessionLocal() as db:
            try:
                delete_account(db, user_id=user_id, password_confirm=confirm_pw)
            except AuthError as e:
                st.error(str(e))
                return
        # Clear local session — pop session_state first, then ask the cookie
        # controller to delete the cookie (it triggers its own rerun once the
        # JS write completes; an explicit st.rerun() here would abort that).
        st.session_state.pop("user", None)
        st.session_state.pop("session_token", None)
        clear_session_token()
        st.success("Account deleted.")


# --- Page entry -------------------------------------------------------------


def render() -> None:
    user = st.session_state.get("user")
    if user is None:
        st.error("Not logged in.")
        return

    _handle_paystack_callback()

    name = user.get("full_name") or ""
    st.title(f"Account — {name}" if name else "Account")
    st.markdown(f"**Email:** {user['email']}")
    st.markdown(f"**Plan:** {user['tier'].title()}")

    st.divider()
    _render_profile_section(UUID(user["id"]))

    st.divider()
    _render_security_section(UUID(user["id"]))

    st.divider()
    _render_subscription_block(UUID(user["id"]))

    st.divider()
    if st.button("Log out"):
        token = st.session_state.get("session_token")
        if token:
            with SessionLocal() as db:
                logout(db, token)
        # Pop session_state before clearing the cookie. The cookie controller
        # triggers its own rerun once the JS clear completes (see login.py).
        st.session_state.pop("user", None)
        st.session_state.pop("session_token", None)
        clear_session_token()

    st.divider()
    _render_danger_zone(UUID(user["id"]))
