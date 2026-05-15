"""Wrapper around streamlit-cookies-controller for the session cookie."""
from __future__ import annotations

import streamlit as st
from streamlit_cookies_controller import CookieController

COOKIE_NAME = "zenkos_session"


@st.cache_resource
def _controller() -> CookieController:
    return CookieController()


def get_session_token() -> str | None:
    """Return the persisted session JWT, or None if not set yet.

    The cookie controller loads asynchronously on first script run, so the
    first call after a hard refresh may return None even with a valid cookie.
    Streamlit will rerun once the cookie has loaded.
    """
    value = _controller().get(COOKIE_NAME)
    if not value:
        return None
    return str(value)


def set_session_token(token: str, max_age_seconds: int) -> None:
    _controller().set(COOKIE_NAME, token, max_age=max_age_seconds, same_site="lax")


def clear_session_token() -> None:
    _controller().remove(COOKIE_NAME)
