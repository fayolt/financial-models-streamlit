"""Wrapper around streamlit-cookies-controller for the session cookie."""
from __future__ import annotations

import streamlit as st
from streamlit_cookies_controller import CookieController

COOKIE_NAME = "numquants_session"


def _controller() -> CookieController:
    """Return a fresh CookieController per call. Do NOT cache the instance.

    Two pitfalls handled here:
    1) `@st.cache_resource` is forbidden because CookieController.__init__
       renders a Streamlit custom component (a widget).
    2) Stashing the instance in `st.session_state` *also* breaks: the
       library pins its in-memory cookie dict at __init__ time. On the
       first script run after a hard refresh the JS component hasn't
       replied yet, so __cookies = {}. When the component later fires a
       rerun, a cached instance still holds the stale empty dict and
       `.get()` keeps returning None — so the user appears logged out.

    The library already caches the *cookie data* in `st.session_state["cookies"]`,
    so re-instantiating per call skips the component round-trip after the
    first call within a script run, then picks up the freshly-loaded data
    on the next rerun.
    """
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
