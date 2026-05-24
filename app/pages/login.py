"""Login page."""
from __future__ import annotations

import streamlit as st

from app.auth.cookie import set_session_token
from app.auth.ratelimit import is_rate_limited, record_failed_attempt
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
    st.markdown(
        '<p style="margin-top:4px;font-size:13px;">'
        'No account? <a href="/signup" target="_self">Sign up</a>'
        '</p>',
        unsafe_allow_html=True,
    )

    if not submitted:
        return
    if not email or not password:
        st.error("Email and password are required.")
        return

    with SessionLocal() as db:
        if is_rate_limited(db, "login"):
            st.error("Too many failed attempts from your location. Please wait a few minutes and try again.")
            return
        try:
            user, token = login(db, email=email, password=password)
        except AuthError as e:
            record_failed_attempt(db, "login")
            st.error(str(e))
            return

    # Populate session_state for immediate auth view, then ask the cookie
    # controller to persist the token. We intentionally do NOT call st.rerun()
    # here — the cookie controller is an async Streamlit component that
    # renders in the browser and triggers its own rerun once the JS cookie
    # write completes. Calling st.rerun() too early aborts the component
    # render and the cookie never persists (the bug we just had).
    st.session_state.user = {
        "id": str(user.id),
        "email": user.email,
        "tier": user.tier,
        "full_name": user.full_name,
        "is_admin": user.is_admin,
    }
    st.session_state.session_token = token
    set_session_token(token, max_age_seconds=SESSION_TTL_SECONDS)
    st.success("Logged in. Loading your dashboard…")


def _render_forgot_link() -> None:
    """Inline link to the forgot-password page, rendered below the form."""
    st.markdown(
        '<p style="margin-top:4px;font-size:13px;">'
        '<a href="/forgot-password" target="_self">Forgot password?</a>'
        '</p>',
        unsafe_allow_html=True,
    )
