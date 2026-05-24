"""Signup page."""
from __future__ import annotations

import streamlit as st

from app.auth.cookie import set_session_token
from app.auth.ratelimit import is_rate_limited, record_failed_attempt
from app.auth.service import AuthError, login, signup_silent
from app.auth.tokens import SESSION_TTL_SECONDS
from app.db import SessionLocal

_BRAND_HEADER = """
<div style="text-align:center;padding:2rem 0 1rem;">
  <div style="font-size:2.5rem;line-height:1;">📊</div>
  <h1 style="color:#16a34a;margin:0.25rem 0 0;font-size:1.6rem;font-weight:700;">NumQuants</h1>
  <p style="color:#64748b;margin:0.25rem 0 0.75rem;font-size:0.875rem;">
    Financial modelling for the African market
  </p>
  <div style="display:flex;flex-wrap:wrap;gap:0.4rem;justify-content:center;margin-bottom:0.5rem;">
    <span style="font-size:0.75rem;color:#475569;background:#f1f5f9;padding:0.2rem 0.65rem;border-radius:1rem;">📊 7 financial models</span>
    <span style="font-size:0.75rem;color:#475569;background:#f1f5f9;padding:0.2rem 0.65rem;border-radius:1rem;">📄 XLSX · PDF · DOCX exports</span>
    <span style="font-size:0.75rem;color:#475569;background:#f1f5f9;padding:0.2rem 0.65rem;border-radius:1rem;">🤖 AI commentary</span>
    <span style="font-size:0.75rem;color:#475569;background:#f1f5f9;padding:0.2rem 0.65rem;border-radius:1rem;">💳 ZAR billing · cancel anytime</span>
  </div>
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
    if "user" in st.session_state:
        st.markdown(_BRAND_HEADER, unsafe_allow_html=True)
        st.markdown(
            "<p style='text-align:center;color:#64748b;'>Loading your dashboard…</p>",
            unsafe_allow_html=True,
        )
        return

    st.markdown(_BRAND_HEADER, unsafe_allow_html=True)

    with st.form("signup_form", clear_on_submit=False):
        full_name = st.text_input("Full name (optional)")
        email = st.text_input("Email", placeholder="you@example.com")
        password = st.text_input("Password", type="password", help="At least 8 characters.")
        confirm = st.text_input("Confirm password", type="password")
        submitted = st.form_submit_button("Create account", type="primary", use_container_width=True)

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
    st.markdown(_FOOTER, unsafe_allow_html=True)

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
            st.error("Too many signup attempts. Please wait a few minutes.")
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
            st.success(
                "Check your inbox — we sent a message to that address with "
                "next steps. If you don't see it within a minute, check spam."
            )
            return

        _, token = login(db, email=email, password=password)

    # Same pattern as login.py — no explicit st.rerun().
    st.session_state.user = {
        "id": str(user.id),
        "email": user.email,
        "tier": user.tier,
        "full_name": user.full_name,
        "is_admin": user.is_admin,
    }
    st.session_state.session_token = token
    set_session_token(token, max_age_seconds=SESSION_TTL_SECONDS)
