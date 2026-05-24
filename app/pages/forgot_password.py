"""Forgot-password page: ask for an email, send a reset link."""
from __future__ import annotations

import streamlit as st

from app.auth.ratelimit import is_rate_limited, record_failed_attempt
from app.auth.service import request_password_reset
from app.db import SessionLocal


_FOOTER = """
<p style="text-align:center;font-size:11px;color:#94a3b8;margin-top:2rem;">
  © 2026 NumQuants &nbsp;·&nbsp;
  <a href="/terms" target="_self" style="color:#94a3b8;">Terms</a> &nbsp;·&nbsp;
  <a href="/privacy" target="_self" style="color:#94a3b8;">Privacy</a>
</p>
"""


def render() -> None:
    st.title("Forgot password")
    st.write("Enter your account email and we'll send you a reset link.")

    with st.form("forgot_form", clear_on_submit=False):
        email = st.text_input("Email", placeholder="you@example.com")
        submitted = st.form_submit_button("Send reset link", type="primary")

    st.markdown(
        '<p style="margin-top:4px;font-size:13px;">'
        '<a href="/login" target="_self">Back to log in</a>'
        '</p>',
        unsafe_allow_html=True,
    )
    st.markdown(_FOOTER, unsafe_allow_html=True)

    if not submitted:
        return
    if not email:
        st.error("Email is required.")
        return

    with SessionLocal() as db:
        if is_rate_limited(db, "reset"):
            st.error("Too many reset requests from your location. Please wait a few minutes.")
            return
        record_failed_attempt(db, "reset")  # count every request, not just failures
        request_password_reset(db, email=email)

    # Always show the same message — don't disclose whether the email exists.
    st.success(
        "If an account exists for that email, a reset link is on its way. "
        "Check your inbox (and spam folder)."
    )
