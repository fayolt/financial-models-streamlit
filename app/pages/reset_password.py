"""Reset-password page: reached via emailed link with ?reset_token=… in URL."""
from __future__ import annotations

import streamlit as st

from app.auth.service import AuthError, complete_password_reset
from app.db import SessionLocal


def render() -> None:
    st.title("Set a new password")

    # On first arrival the token lives in ?reset_token=…. Move it into
    # session state and clear the query string so it doesn't stay in
    # browser history, referrer headers, or analytics.
    if "reset_token" in st.query_params:
        st.session_state["_reset_token"] = st.query_params["reset_token"]
        st.query_params.clear()
        st.rerun()

    token = st.session_state.get("_reset_token")
    if not token:
        st.error("Missing reset token. Use the link from the password-reset email.")
        return

    with st.form("reset_form", clear_on_submit=False):
        password = st.text_input("New password", type="password", help="At least 8 characters.")
        confirm = st.text_input("Confirm new password", type="password")
        submitted = st.form_submit_button("Set new password", type="primary")

    if not submitted:
        return
    if not password or not confirm:
        st.error("Both password fields are required.")
        return
    if password != confirm:
        st.error("Passwords do not match.")
        return

    with SessionLocal() as db:
        try:
            complete_password_reset(db, token=token, new_password=password)
        except AuthError as e:
            st.error(str(e))
            return

    # Single-use: consume the token so refreshing this page can't retry.
    st.session_state.pop("_reset_token", None)
    st.success("Password updated. You can now log in with your new password.")
    st.link_button("Go to log in", url="/login", type="primary")
