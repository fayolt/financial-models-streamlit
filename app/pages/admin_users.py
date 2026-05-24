"""Admin · Users — search, view detail, adjust tier, refund, manage admin flag."""
from __future__ import annotations

from uuid import UUID

import pandas as pd
import streamlit as st

from app.admin import (
    NotAdminError,
    get_user_detail,
    issue_refund_for_user,
    list_users,
    recent_audit_entries_for_user,
    require_admin,
    set_user_admin,
    set_user_tier,
)
from app.db import SessionLocal


_TIERS = ("free", "pro", "enterprise")


def render() -> None:
    try:
        require_admin(st.session_state.get("user"))
    except NotAdminError as e:
        st.error(str(e))
        return

    actor_id = UUID(st.session_state["user"]["id"])

    st.title("Admin · Users")

    search = st.text_input("Search by email", placeholder="Type any substring…").strip() or None

    with SessionLocal() as db:
        users = list_users(db, search=search, limit=200)

    if not users:
        st.info("No matching users.")
        return

    summary = pd.DataFrame(
        [
            {
                "email": u.email,
                "tier": u.tier,
                "admin": u.is_admin,
                "active": u.is_active,
                "created": u.created_at,
            }
            for u in users
        ]
    )
    st.dataframe(summary, use_container_width=True, hide_index=True)

    st.divider()

    options = [u.email for u in users]
    chosen = st.selectbox("Inspect a user", options=options, index=0)
    if not chosen:
        return
    target = next(u for u in users if u.email == chosen)

    with SessionLocal() as db:
        detail = get_user_detail(db, target.id)
    if detail is None:
        st.warning("User no longer exists.")
        return

    u = detail["user"]
    st.subheader(u.email)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Tier", u.tier.title())
    c2.metric("Admin", "Yes" if u.is_admin else "No")
    c3.metric("Active", "Yes" if u.is_active else "No")
    c4.metric("Created", u.created_at.date().isoformat())

    _render_tier_section(u, actor_id)
    _render_admin_section(u, actor_id)
    _render_subscriptions(detail["subscriptions"])
    _render_refund_section(u, detail["refunds"], actor_id)
    _render_recent_runs(detail["recent_runs"])
    _render_audit_log(u)


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def _render_tier_section(user, actor_id: UUID) -> None:
    st.markdown("**Adjust tier** (comping or testing)")
    new_tier = st.selectbox(
        "New tier",
        options=list(_TIERS),
        index=_TIERS.index(user.tier),
        key=f"tier-{user.id}",
    )
    if st.button("Apply tier change", disabled=(new_tier == user.tier), key=f"apply-tier-{user.id}"):
        with SessionLocal() as db:
            set_user_tier(db, user.id, new_tier, actor_id=actor_id)
        st.success(f"Tier set to {new_tier}.")
        st.rerun()


def _render_admin_section(user, actor_id: UUID) -> None:
    st.markdown("**Admin access**")
    is_self = user.id == actor_id

    if user.is_admin:
        if is_self:
            st.caption("You can't demote yourself from here — use the CLI on a server.")
            return
        if st.button(
            "Revoke admin",
            type="secondary",
            key=f"revoke-admin-{user.id}",
        ):
            with SessionLocal() as db:
                try:
                    set_user_admin(db, user.id, False, actor_id=actor_id)
                except ValueError as e:
                    st.error(str(e))
                    return
            st.success(f"Revoked admin for {user.email}.")
            st.rerun()
    else:
        confirm_key = f"confirm-grant-admin-{user.id}"
        if st.session_state.get(confirm_key):
            st.warning(
                f"Grant admin to **{user.email}**? They'll be able to issue refunds, "
                "change tiers, and grant admin to others."
            )
            c1, c2 = st.columns(2)
            with c1:
                if st.button(
                    "Yes, grant admin",
                    type="primary",
                    key=f"confirm-yes-{user.id}",
                    use_container_width=True,
                ):
                    with SessionLocal() as db:
                        set_user_admin(db, user.id, True, actor_id=actor_id)
                    st.session_state.pop(confirm_key, None)
                    st.success(f"Granted admin to {user.email}.")
                    st.rerun()
            with c2:
                if st.button("Cancel", key=f"confirm-no-{user.id}", use_container_width=True):
                    st.session_state.pop(confirm_key, None)
                    st.rerun()
        else:
            if st.button("Grant admin", key=f"grant-admin-{user.id}"):
                st.session_state[confirm_key] = True
                st.rerun()


def _render_subscriptions(subs) -> None:
    if not subs:
        return
    st.markdown("**Subscriptions**")
    sub_df = pd.DataFrame(
        [
            {
                "plan": p.name if p else "—",
                "status": s.status,
                "paystack_sub": s.paystack_subscription_code or "—",
                "created": s.created_at,
                "cancelled": s.cancelled_at,
            }
            for s, p in subs
        ]
    )
    st.dataframe(sub_df, use_container_width=True, hide_index=True)


def _render_refund_section(user, refunds, actor_id: UUID) -> None:
    st.markdown("**Refunds**")
    if refunds:
        ref_df = pd.DataFrame(
            [
                {
                    "ref": r.paystack_transaction_reference,
                    "amount": (
                        f"{r.currency} {r.amount_minor_units / 100:,.2f}"
                        if r.amount_minor_units
                        else f"{r.currency} (full)"
                    ),
                    "status": r.status,
                    "reason": (r.reason or "")[:60],
                    "created": r.created_at,
                    "processed": r.processed_at,
                    "error": (r.error_message or "")[:60],
                }
                for r in refunds
            ]
        )
        st.dataframe(ref_df, use_container_width=True, hide_index=True)
    else:
        st.caption("No refunds issued for this user.")

    with st.expander("Issue a refund"):
        st.caption(
            "Look up the transaction reference in the Paystack dashboard "
            "(Customers → this user → Transactions)."
        )
        with st.form(f"refund-form-{user.id}", clear_on_submit=True):
            ref = st.text_input("Transaction reference", placeholder="T123456789").strip()
            full = st.checkbox("Full refund", value=True, key=f"full-{user.id}")
            amount_zar = st.number_input(
                "Amount (ZAR)",
                min_value=0.0,
                value=0.0,
                step=10.0,
                format="%.2f",
                disabled=full,
                help="Only used when 'Full refund' is unchecked.",
            )
            reason = st.text_area(
                "Reason (required, stored for compliance)",
                placeholder="e.g. Customer requested cancellation within 14-day window.",
            ).strip()
            submitted = st.form_submit_button("Issue refund", type="primary")

        if not submitted:
            return
        if not ref:
            st.error("Transaction reference is required.")
            return
        if not reason:
            st.error("Reason is required.")
            return

        amount_minor: int | None = None
        if not full:
            if amount_zar <= 0:
                st.error("Amount must be positive (or check 'Full refund').")
                return
            amount_minor = int(round(amount_zar * 100))

        with SessionLocal() as db:
            try:
                refund = issue_refund_for_user(
                    db,
                    user_id=user.id,
                    transaction_reference=ref,
                    reason=reason,
                    amount_minor_units=amount_minor,
                    currency="ZAR",
                    actor_id=actor_id,
                )
            except ValueError as e:
                st.error(str(e))
                return
            except RuntimeError as e:
                st.error(str(e))
                return

        st.success(
            f"Refund submitted to Paystack (id `{refund.paystack_refund_id or 'pending'}`). "
            "Status will flip to 'processed' when the webhook arrives."
        )
        st.rerun()


def _render_recent_runs(runs) -> None:
    if not runs:
        return
    st.markdown("**Recent report runs** (last 25)")
    runs_df = pd.DataFrame(
        [
            {
                "model": r.model_slug,
                "format": r.format,
                "status": r.status,
                "bytes": r.bytes_size or 0,
                "started": r.started_at,
                "completed": r.completed_at,
                "error": (r.error_message or "")[:60],
            }
            for r in runs
        ]
    )
    st.dataframe(runs_df, use_container_width=True, hide_index=True)


def _render_audit_log(user) -> None:
    with SessionLocal() as db:
        entries = recent_audit_entries_for_user(db, user.id, limit=25)
    if not entries:
        return
    st.markdown("**Audit log** (last 25 actions on this user)")
    log_df = pd.DataFrame(
        [
            {
                "when": e.created_at,
                "action": e.action,
                "actor_id": str(e.actor_id)[:8] if e.actor_id else "—",
                "payload": str(e.payload or {})[:200],
            }
            for e in entries
        ]
    )
    st.dataframe(log_df, use_container_width=True, hide_index=True)
