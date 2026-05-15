"""Forgot-password page: ask for an email, send a reset link."""
from __future__ import annotations

import streamlit as st

from app.auth.service import request_password_reset
from app.db import SessionLocal


def render() -> None:
    st.title("Forgot password")
    st.write("Enter your account email and we'll send you a reset link.")

    with st.form("forgot_form", clear_on_submit=False):
        email = st.text_input("Email", placeholder="you@example.com")
        submitted = st.form_submit_button("Send reset link", type="primary")

    if not submitted:
        return
    if not email:
        st.error("Email is required.")
        return

    with SessionLocal() as db:
        request_password_reset(db, email=email)

    # Always show the same message — don't disclose whether the email exists.
    st.success(
        "If an account exists for that email, a reset link is on its way. "
        "Check your inbox (and spam folder)."
    )
