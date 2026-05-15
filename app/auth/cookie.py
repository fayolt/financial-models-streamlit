"""Session cookie wrapper.

READ goes through `st.context.cookies` which is populated from the HTTP
request headers on every script run — synchronous and reliable from the
first paint. WRITE goes through streamlit-cookies-controller because we
need a JS round-trip to update `document.cookie` in the browser, but the
async delay there is harmless: the in-process `st.session_state` carries
the active user for the current run, and the next request will read the
freshly-written cookie via the headers.
"""
from __future__ import annotations

import streamlit as st
from streamlit_cookies_controller import CookieController

COOKIE_NAME = "numquants_session"


def get_session_token() -> str | None:
    """Synchronous, header-based read of the session cookie."""
    try:
        value = st.context.cookies.get(COOKIE_NAME)
    except Exception:
        value = None
    if not value:
        return None
    return str(value)


def set_session_token(token: str, max_age_seconds: int) -> None:
    CookieController().set(
        COOKIE_NAME, token, max_age=max_age_seconds, same_site="lax"
    )


def clear_session_token() -> None:
    CookieController().remove(COOKIE_NAME)
