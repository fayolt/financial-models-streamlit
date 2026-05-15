"""Signup page."""
from __future__ import annotations

import streamlit as st

from app.auth.cookie import set_session_token
from app.auth.service import AuthError, login, signup
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

    if not submitted:
        return
    if not email or not password:
        st.error("Email and password are required.")
        return
    if password != confirm:
        st.error("Passwords do not match.")
        return

    with SessionLocal() as db:
        try:
            signup(db, email=email, password=password, full_name=full_name or None)
            user, token = login(db, email=email, password=password)
        except AuthError as e:
            st.error(str(e))
            return

    set_session_token(token, max_age_seconds=SESSION_TTL_SECONDS)
    st.session_state.user = {
        "id": str(user.id),
        "email": user.email,
        "tier": user.tier,
        "full_name": user.full_name,
    }
    st.session_state.session_token = token
    st.success("Account created — welcome!")
    st.rerun()
