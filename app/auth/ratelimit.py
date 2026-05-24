"""IP-based rate limiting for auth endpoints.

Backed by Postgres so limits survive Streamlit script reruns and are shared
across multiple container instances. Each window is 5 minutes; old rows are
cleaned up lazily on every check.

Usage (in a page render function):
    with SessionLocal() as db:
        if is_rate_limited(db, "login"):
            st.error("Too many attempts. Please wait a few minutes.")
            return
        try:
            ...  # attempt the auth operation
        except AuthError:
            record_failed_attempt(db, "login")
            ...
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import streamlit as st
from sqlalchemy.orm import Session

from app.db.models import AuthRateLimit

_log = logging.getLogger("app.auth.ratelimit")

# (max_failures_per_window, window_minutes)
_LIMITS: dict[str, tuple[int, int]] = {
    "login": (10, 5),
    "signup": (5, 5),
    "reset": (5, 5),
}


def _client_ip() -> str:
    try:
        headers = st.context.headers
        forwarded = headers.get("X-Forwarded-For") or headers.get("X-Real-Ip") or ""
        return forwarded.split(",")[0].strip() or "unknown"
    except Exception:
        return "unknown"


def _window_start(window_minutes: int) -> datetime:
    now = datetime.now(timezone.utc)
    truncated = (now.minute // window_minutes) * window_minutes
    return now.replace(minute=truncated, second=0, microsecond=0)


def is_rate_limited(db: Session, action: str, ip: str | None = None) -> bool:
    """Return True if this IP has exceeded the failure threshold for `action`."""
    if ip is None:
        ip = _client_ip()
    if ip == "unknown":
        return False

    max_failures, window_minutes = _LIMITS.get(action, (5, 5))
    window = _window_start(window_minutes)

    # Lazy cleanup: remove windows older than 1 hour.
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    db.query(AuthRateLimit).filter(AuthRateLimit.window_start < cutoff).delete(
        synchronize_session=False
    )

    row = db.get(AuthRateLimit, (ip, action, window))
    limited = (row.count if row else 0) >= max_failures
    if limited:
        _log.warning("rate limit hit: ip=%s action=%s count=%s", ip, action, row.count if row else 0)
    return limited


def record_failed_attempt(db: Session, action: str, ip: str | None = None) -> None:
    """Increment the failure counter for this IP+action in the current window."""
    if ip is None:
        ip = _client_ip()
    if ip == "unknown":
        return

    _, window_minutes = _LIMITS.get(action, (5, 5))
    window = _window_start(window_minutes)

    row = db.get(AuthRateLimit, (ip, action, window))
    if row is None:
        db.add(AuthRateLimit(ip=ip, action=action, window_start=window, count=1))
    else:
        row.count += 1
    db.commit()
