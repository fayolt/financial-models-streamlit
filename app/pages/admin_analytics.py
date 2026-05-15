"""Admin · Analytics — KPIs, signup curve, report usage."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.admin import (
    NotAdminError,
    mrr_minor_units,
    reports_by_model,
    require_admin,
    signups_by_day,
    tier_distribution,
    total_active_users,
)
from app.db import SessionLocal


def render() -> None:
    try:
        require_admin(st.session_state.get("user"))
    except NotAdminError as e:
        st.error(str(e))
        return

    st.title("Admin · Analytics")

    with SessionLocal() as db:
        users_count = total_active_users(db)
        tiers = tier_distribution(db)
        mrr_kobo = mrr_minor_units(db)
        signups = signups_by_day(db, days=30)
        reports = reports_by_model(db, days=30)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Active users", f"{users_count:,}")
    c2.metric("Pro users", f"{tiers.get('pro', 0):,}")
    c3.metric("Enterprise users", f"{tiers.get('enterprise', 0):,}")
    c4.metric("MRR (NGN)", f"{mrr_kobo / 100:,.0f}")

    st.divider()
    st.subheader("Signups — last 30 days")
    if signups:
        sig_df = pd.DataFrame(signups, columns=["day", "signups"]).set_index("day")
        st.line_chart(sig_df, y="signups", height=240)
    else:
        st.info("No signups in the last 30 days.")

    st.divider()
    st.subheader("Tier mix")
    if tiers:
        tier_df = pd.DataFrame(
            sorted(tiers.items(), key=lambda kv: ("free", "pro", "enterprise").index(kv[0])),
            columns=["tier", "users"],
        ).set_index("tier")
        st.bar_chart(tier_df, y="users", height=220)
    else:
        st.info("No users yet.")

    st.divider()
    st.subheader("Reports by model — last 30 days (successful)")
    if reports:
        rep_df = pd.DataFrame(
            list(reports.items()), columns=["model", "reports"]
        ).set_index("model")
        st.bar_chart(rep_df, y="reports", height=240)
    else:
        st.info("No reports generated in the last 30 days.")
