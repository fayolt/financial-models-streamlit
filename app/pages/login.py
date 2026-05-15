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

    set_session_token(token, max_age_seconds=SESSION_TTL_SECONDS)
    st.session_state.user = {
        "id": str(user.id),
        "email": user.email,
        "tier": user.tier,
        "full_name": user.full_name,
    }
    st.session_state.session_token = token
    st.success("Logged in. Loading your dashboard…")
    st.rerun()
