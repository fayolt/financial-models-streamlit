"""Login page."""
from __future__ import annotations

import streamlit as st

from app.auth.cookie import set_session_token
from app.auth.ratelimit import is_rate_limited, record_failed_attempt
from app.auth.service import AuthError, login
from app.auth.tokens import SESSION_TTL_SECONDS
from app.db import SessionLocal

_BRAND_HEADER = """
<div style="text-align:center;padding:2rem 0 1.5rem;">
  <div style="font-size:2.5rem;line-height:1;">📊</div>
  <h1 style="color:#16a34a;margin:0.25rem 0 0;font-size:1.6rem;font-weight:700;">NumQuants</h1>
  <p style="color:#64748b;margin:0.25rem 0 0;font-size:0.875rem;">
    Financial modelling for the African market
  </p>
</div>
"""

_FOOTER = """
<p style="text-align:center;font-size:11px;color:#94a3b8;margin-top:2rem;">
  © 2026 NumQuants &nbsp;·&nbsp;
  <a href="/terms" target="_self" style="color:#94a3b8;">Terms</a> &nbsp;·&nbsp;
  <a href="/privacy" target="_self" style="color:#94a3b8;">Privacy</a> &nbsp;·&nbsp;
  <a href="mailto:support@numquants.com" style="color:#94a3b8;">Support</a>
</p>
"""


def render() -> None:
    # If session was just set (cookie controller pending its first rerun),
    # show a clean loading screen instead of the form.
    if "user" in st.session_state:
        st.markdown(_BRAND_HEADER, unsafe_allow_html=True)
        st.markdown(
            "<p style='text-align:center;color:#64748b;'>Loading your dashboard…</p>",
            unsafe_allow_html=True,
        )
        return

    st.markdown(_BRAND_HEADER, unsafe_allow_html=True)

    with st.form("login_form", clear_on_submit=False):
        email = st.text_input("Email", placeholder="you@example.com")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in", type="primary", use_container_width=True)

    _render_forgot_link()
    st.markdown(
        '<p style="margin-top:4px;font-size:13px;">'
        'No account? <a href="/signup" target="_self">Sign up free</a>'
        '</p>',
        unsafe_allow_html=True,
    )
    st.markdown(_FOOTER, unsafe_allow_html=True)

    if not submitted:
        return
    if not email or not password:
        st.error("Email and password are required.")
        return

    with SessionLocal() as db:
        if is_rate_limited(db, "login"):
            st.error("Too many failed attempts. Please wait a few minutes and try again.")
            return
        try:
            user, token = login(db, email=email, password=password)
        except AuthError as e:
            record_failed_attempt(db, "login")
            st.error(str(e))
            return

    # Populate session_state first, then persist the cookie. We do NOT call
    # st.rerun() — the cookie controller triggers its own rerun once its JS
    # write completes. An explicit rerun aborts the component before it writes.
    st.session_state.user = {
        "id": str(user.id),
        "email": user.email,
        "tier": user.tier,
        "full_name": user.full_name,
        "is_admin": user.is_admin,
    }
    st.session_state.session_token = token
    set_session_token(token, max_age_seconds=SESSION_TTL_SECONDS)


def _render_forgot_link() -> None:
    st.markdown(
        '<p style="margin-top:4px;font-size:13px;">'
        '<a href="/forgot-password" target="_self">Forgot password?</a>'
        '</p>',
        unsafe_allow_html=True,
    )
