"""Admin · Users — search, view detail, adjust tier."""
from __future__ import annotations

from uuid import UUID

import pandas as pd
import streamlit as st

from app.admin import (
    NotAdminError,
    get_user_detail,
    list_users,
    require_admin,
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

    # Tier adjustment
    st.markdown("**Adjust tier** (comping or testing)")
    new_tier = st.selectbox(
        "New tier", options=list(_TIERS), index=_TIERS.index(u.tier), key=f"tier-{u.id}"
    )
    if st.button("Apply tier change", disabled=(new_tier == u.tier)):
        with SessionLocal() as db:
            set_user_tier(db, u.id, new_tier)
        st.success(f"Tier set to {new_tier}.")
        st.rerun()

    # Subscriptions
    subs = detail["subscriptions"]
    if subs:
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

    # Report runs
    runs = detail["recent_runs"]
    if runs:
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
