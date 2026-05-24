"""Signup page."""
from __future__ import annotations

import streamlit as st

from app.auth.cookie import set_session_token
from app.auth.ratelimit import is_rate_limited, record_failed_attempt
from app.auth.service import AuthError, login, signup_silent
from app.auth.tokens import SESSION_TTL_SECONDS
from app.db import SessionLocal


def render() -> None:
    st.title("Sign up")
    st.write("Create an account to run financial models and download reports.")

    with st.form("signup_form", clear_on_submit=False):
        full_name = st.text_input("Full name (optional)")
        email = st.text_input("Email", placeholder="you@example.com")
        password = st.text_input("Password", type="password", help="At least 8 characters.")
        confirm = st.text_input("Confirm password", type="password")
        submitted = st.form_submit_button("Create account", type="primary")

    st.markdown(
        '<p style="margin-top:4px;font-size:13px;">'
        'Already have an account? <a href="/login" target="_self">Log in</a>'
        '</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p style="margin-top:2px;font-size:11px;color:gray;">'
        'By creating an account you agree to our '
        '<a href="/terms" target="_self">Terms of Service</a> and '
        '<a href="/privacy" target="_self">Privacy Policy</a>.'
        '</p>',
        unsafe_allow_html=True,
    )

    if not submitted:
        return
    if not email or not password:
        st.error("Email and password are required.")
        return
    if password != confirm:
        st.error("Passwords do not match.")
        return

    with SessionLocal() as db:
        if is_rate_limited(db, "signup"):
            st.error("Too many signup attempts from your location. Please wait a few minutes.")
            return
        try:
            user = signup_silent(
                db, email=email, password=password, full_name=full_name or None
            )
        except AuthError as e:
            record_failed_attempt(db, "signup")
            st.error(str(e))
            return

        if user is None:
            # Email already on file. Don't disclose that — show the same
            # response a brand-new signup would see, and email the address
            # owner via signup_silent so they can recover the account.
            st.success(
                "Check your inbox — we sent a message to that address with "
                "next steps. If you don't see it within a minute, check spam."
            )
            return

        _, token = login(db, email=email, password=password)

    # Populate session_state first, then let the cookie controller persist
    # the token asynchronously. See login.py for the rationale on omitting
    # st.rerun() — the controller triggers its own rerun once the JS cookie
    # write completes; calling st.rerun() here would abort that.
    st.session_state.user = {
        "id": str(user.id),
        "email": user.email,
        "tier": user.tier,
        "full_name": user.full_name,
        "is_admin": user.is_admin,
    }
    st.session_state.session_token = token
    set_session_token(token, max_age_seconds=SESSION_TTL_SECONDS)
    st.success("Account created — welcome!")
