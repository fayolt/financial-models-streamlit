"""Account page with profile info and logout."""
from __future__ import annotations

import streamlit as st

from app.auth.cookie import clear_session_token
from app.auth.service import logout
from app.db import SessionLocal


def render() -> None:
    user = st.session_state.get("user")
    if user is None:
        st.error("Not logged in.")
        return

    st.title("Account")

    st.markdown(f"**Email:** {user['email']}")
    if user.get("full_name"):
        st.markdown(f"**Name:** {user['full_name']}")
    st.markdown(f"**Subscription tier:** {user['tier'].title()}")

    st.divider()

    st.subheader("Subscription")
    if user["tier"] == "free":
        st.info("You're on the Free tier. Upgrade to export reports (Pro) or unlock PDFs and AI commentary (Enterprise).")
        st.button("Upgrade", disabled=True, help="Coming in Phase 3 (Paystack)")
    else:
        st.success(f"{user['tier'].title()} tier — billing managed via Paystack.")
        st.button("Manage subscription", disabled=True, help="Coming in Phase 3 (Paystack)")

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
