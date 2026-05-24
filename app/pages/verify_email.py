"""Email-verification landing page.

Triggered by the link in the signup email. Reads `verify_email_token` from
the query string, calls the auth service to mark the user verified, and
shows a friendly status. Works whether the user is currently logged in or
not — verification is idempotent.
"""
from __future__ import annotations

import streamlit as st

from app.auth.service import AuthError, confirm_email_verification
from app.db import SessionLocal


def render() -> None:
    st.title("Email verification")

    token = st.query_params.get("verify_email_token")
    if not token:
        st.error("This page is for verifying your email — open the link from your signup email.")
        return

    # Clear the token from the URL bar so it doesn't sit in browser history.
    st.query_params.clear()

    with SessionLocal() as db:
        try:
            user = confirm_email_verification(db, token=token)
        except AuthError as e:
            st.error(str(e))
            st.caption("If the link is older than 48 hours, log in and request a new verification email from your account page.")
            return

    st.success(f"Email verified: **{user.email}**.")
    st.caption("You can now subscribe to a paid plan.")
    if "user" not in st.session_state:
        st.link_button("Log in", url="/login", type="primary")
