"""Reset-password page: reached via emailed link with ?reset_token=… in URL."""
from __future__ import annotations

import streamlit as st

from app.auth.service import AuthError, complete_password_reset
from app.db import SessionLocal


def render() -> None:
    st.title("Set a new password")

    token = st.query_params.get("reset_token")
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

    st.query_params.clear()
    st.success("Password updated. You can now log in with your new password.")
    st.link_button("Go to log in", url="/login", type="primary")
