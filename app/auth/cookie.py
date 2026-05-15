"""Session cookie wrapper.

READ: ``st.context.cookies`` (Streamlit's server-side accessor populated
from the HTTP request's Cookie header). Synchronous, available from the
first script run — no JS round-trip needed.

WRITE: direct JS injection via ``st.components.v1.html``. The injected
script writes to ``window.parent.document.cookie`` and then navigates
the top-level window. We previously used ``streamlit-cookies-controller``
for writes, but its iframe-mediated set raced with the post-login
``st.rerun()`` and dropped cookies before they could persist. Bundling
the cookie write + page navigation into one JS block makes the sequence
deterministic: cookie is in the jar before the next HTTP request fires.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import streamlit as st
import streamlit.components.v1 as components

COOKIE_NAME = "numquants_session"


# --- READ --------------------------------------------------------------------


def get_session_token() -> str | None:
    """Synchronous read of the session cookie from request headers."""
    try:
        value = st.context.cookies.get(COOKIE_NAME)
    except Exception:
        value = None
    return str(value) if value else None


# --- WRITE (via JS injection) ------------------------------------------------


def _http_expires(seconds_from_now: int) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(seconds=seconds_from_now)
    ).strftime("%a, %d %b %Y %H:%M:%S GMT")


def _cookie_string(name: str, value: str, expires_http: str) -> str:
    """Build the `Set-Cookie`-style string to assign to document.cookie."""
    return f"{name}={value}; path=/; expires={expires_http}; SameSite=Lax"


def _inject(js_body: str) -> None:
    """Render a zero-sized HTML/JS component. Used for cookie ops + redirects."""
    components.html(
        f"<script>(function(){{{js_body}}})();</script>",
        height=0,
        width=0,
    )


def set_session_and_redirect(
    token: str, max_age_seconds: int, redirect_path: str = "/"
) -> None:
    """Set the session cookie and navigate the top-level page in one shot.

    Use in place of ``set_session_token(...) + st.rerun()``. The redirect
    triggers a fresh HTTP request that carries the new cookie, so
    ``_hydrate_user_from_cookie`` on the next page load can read it via
    ``st.context.cookies`` immediately."""
    cookie = _cookie_string(COOKIE_NAME, token, _http_expires(max_age_seconds))
    js = f"""
        var d = (window.parent && window.parent.document) || document;
        d.cookie = {json.dumps(cookie)};
        var w = window.parent || window;
        w.location.href = {json.dumps(redirect_path)};
    """
    _inject(js)


def clear_session_and_redirect(redirect_path: str = "/") -> None:
    """Delete the session cookie and navigate the top-level page."""
    expired = _cookie_string(COOKIE_NAME, "", "Thu, 01 Jan 1970 00:00:00 GMT")
    js = f"""
        var d = (window.parent && window.parent.document) || document;
        d.cookie = {json.dumps(expired)};
        var w = window.parent || window;
        w.location.href = {json.dumps(redirect_path)};
    """
    _inject(js)


# --- Back-compat shims --------------------------------------------------------
# These still exist for any caller that doesn't need to redirect (e.g. unit
# tests). They're racy when followed by ``st.rerun()``; prefer the
# ``*_and_redirect`` variants in user-facing flows.


def set_session_token(token: str, max_age_seconds: int) -> None:
    cookie = _cookie_string(COOKIE_NAME, token, _http_expires(max_age_seconds))
    _inject(
        f"""var d = (window.parent && window.parent.document) || document;
        d.cookie = {json.dumps(cookie)};"""
    )


def clear_session_token() -> None:
    expired = _cookie_string(COOKIE_NAME, "", "Thu, 01 Jan 1970 00:00:00 GMT")
    _inject(
        f"""var d = (window.parent && window.parent.document) || document;
        d.cookie = {json.dumps(expired)};"""
    )
