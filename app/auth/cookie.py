"""Session cookie wrapper.

READ: ``st.context.cookies`` (Streamlit's server-side accessor populated
from the HTTP request's Cookie header).

WRITE: direct JS injection via ``st.components.v1.html`` that calls
``window.parent.document.cookie``. We previously tried to do a full
``window.parent.location.href`` redirect from inside the injected
iframe, but Streamlit's components.html iframes are sandboxed without
``allow-top-navigation`` — the redirect is silently blocked. So we
just write the cookie and rely on the caller's ``st.rerun()`` to
re-route through the authenticated nav. The cookie persists in the
browser jar regardless; on the next HTTP request (refresh, new tab),
``st.context.cookies`` picks it up.
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
    """Render a zero-sized HTML/JS component."""
    components.html(
        f"<script>(function(){{{js_body}}})();</script>",
        height=0,
        width=0,
    )


def set_session_token(token: str, max_age_seconds: int) -> None:
    """Write the session cookie to the browser via injected JS."""
    cookie = _cookie_string(COOKIE_NAME, token, _http_expires(max_age_seconds))
    _inject(
        f"""var d = (window.parent && window.parent.document) || document;
        d.cookie = {json.dumps(cookie)};"""
    )


def clear_session_token() -> None:
    """Delete the session cookie via injected JS."""
    expired = _cookie_string(COOKIE_NAME, "", "Thu, 01 Jan 1970 00:00:00 GMT")
    _inject(
        f"""var d = (window.parent && window.parent.document) || document;
        d.cookie = {json.dumps(expired)};"""
    )
