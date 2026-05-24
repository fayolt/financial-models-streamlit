"""Login page."""
from __future__ import annotations

import streamlit as st

from app.auth.cookie import set_session_token
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
        try:
            user, token = login(db, email=email, password=password)
        except AuthError as e:
            st.error(str(e))
            return

    # Write cookie via injected JS (persists to the browser jar for future
    # HTTP requests), AND populate session_state immediately so the next
    # rerun renders the authenticated nav without depending on a fresh
    # HTTP round-trip.
    set_session_token(token, max_age_seconds=SESSION_TTL_SECONDS)
    st.session_state.user = {
        "id": str(user.id),
        "email": user.email,
        "tier": user.tier,
        "full_name": user.full_name,
        "is_admin": user.is_admin,
    }
    st.session_state.session_token = token
    st.success("Logged in. Loading your dashboard…")
    st.rerun()


def _render_forgot_link() -> None:
    """Inline link to the forgot-password page, rendered below the form."""
    st.markdown(
        '<p style="margin-top:4px;font-size:13px;">'
        '<a href="/forgot-password" target="_self">Forgot password?</a>'
        '</p>',
        unsafe_allow_html=True,
    )
