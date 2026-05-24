"""Session cookie wrapper.

READ: ``st.context.cookies`` (Streamlit's server-side accessor populated
from the HTTP request's Cookie header). Synchronous and reliable.

WRITE: ``streamlit-cookies-controller`` — a Streamlit component that
runs JS in a proper component iframe with access to the parent's
``document.cookie``. We previously used raw ``st.components.v1.html``
JS injection, but Streamlit 1.57 tightened iframe sandboxing and
``window.parent.document.cookie`` access started silently failing —
users got fresh login sessions on every refresh.

The cookie persists in the browser jar after ``set_session_token``;
on the next HTTP request (refresh, new tab) ``st.context.cookies``
picks it up synchronously.
"""
from __future__ import annotations

import os

import streamlit as st
from streamlit_cookies_controller import CookieController

COOKIE_NAME = "numquants_session"

# Secure flag enabled on HTTPS deployments. Localhost dev is HTTP so we
# leave it off there (browsers would reject Secure cookies over HTTP).
_SECURE = os.environ.get("APP_ENV", "development").lower() in {"staging", "production"}


def _controller() -> CookieController:
    """Get-or-create the page-scoped CookieController.

    The controller renders a hidden iframe component the first time it's
    constructed in a script run; reusing the same instance across calls in
    the same run avoids re-rendering it twice.
    """
    if "_cookie_controller" not in st.session_state:
        st.session_state["_cookie_controller"] = CookieController()
    return st.session_state["_cookie_controller"]


# --- READ --------------------------------------------------------------------


def get_session_token() -> str | None:
    """Synchronous read of the session cookie from the HTTP request headers."""
    try:
        value = st.context.cookies.get(COOKIE_NAME)
    except Exception:
        value = None
    return str(value) if value else None


# --- WRITE (via Streamlit component) -----------------------------------------


def set_session_token(token: str, max_age_seconds: int) -> None:
    """Persist the session cookie to the browser."""
    _controller().set(
        COOKIE_NAME,
        token,
        max_age=max_age_seconds,
        path="/",
        same_site="lax",
        secure=_SECURE,
    )


def clear_session_token() -> None:
    """Delete the session cookie from the browser."""
    _controller().remove(
        COOKIE_NAME,
        path="/",
        same_site="lax",
        secure=_SECURE,
    )
