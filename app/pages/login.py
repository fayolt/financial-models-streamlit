"""Login page."""
from __future__ import annotations

import streamlit as st

from app.auth.cookie import set_session_and_redirect
from app.auth.service import AuthError, login
from app.auth.tokens import SESSION_TTL_SECONDS
from app.db import SessionLocal


def render() -> None:
    st.title("Log in")
    st.write("Welcome back. Log in to access your financial models.")

    with st.form("login_form", clear_on_submit=False):
        email = st.text_input("Email", placeholder="you@example.com")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in", type="primary")

    _render_forgot_link()

    if not submitted:
        return
    if not email or not password:
        st.error("Email and password are required.")
        return

    with SessionLocal() as db:
        try:
            user, token = login(db, email=email, password=password)
        except AuthError as e:
            st.error(str(e))
            return

    # Set the cookie AND redirect in one JS block. The fresh HTTP request
    # carries the cookie so st.context.cookies sees it on first read.
    # session_state will be repopulated by _hydrate_user_from_cookie.
    st.success("Logged in. Loading your dashboard…")
    set_session_and_redirect(
        token, max_age_seconds=SESSION_TTL_SECONDS, redirect_path="/"
    )
    st.stop()


def _render_forgot_link() -> None:
    """Inline link to the forgot-password page, rendered below the form."""
    st.markdown(
        '<p style="margin-top:4px;font-size:13px;">'
        '<a href="/forgot-password" target="_self">Forgot password?</a>'
        '</p>',
        unsafe_allow_html=True,
    )
