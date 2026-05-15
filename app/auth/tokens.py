"""JWT session token issuing and verification."""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import jwt

JWT_SECRET: str = os.environ.get(
    "JWT_SECRET",
    "dev-secret-CHANGE-ME-in-production-must-exceed-32-bytes",
)
JWT_ALGORITHM: str = os.environ.get("JWT_ALGORITHM", "HS256")
SESSION_TTL_SECONDS: int = int(
    os.environ.get("SESSION_TTL_SECONDS", str(30 * 24 * 3600))
)


class InvalidTokenError(Exception):
    """Raised when a JWT fails signature, expiry, or claim validation."""


def issue_session_token(
    *,
    user_id: UUID,
    email: str,
    ttl_seconds: int | None = None,
) -> tuple[str, datetime]:
    """Return (token, expires_at) for a freshly minted session JWT.

    `expires_at` is timezone-aware UTC so callers can persist it directly.
    """
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=ttl_seconds or SESSION_TTL_SECONDS)
    payload = {
        "sub": str(user_id),
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token, expires_at


def verify_session_token(token: str) -> dict[str, Any]:
    """Decode and validate a session JWT. Raises InvalidTokenError on failure."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError as e:
        raise InvalidTokenError(str(e)) from e


def token_hash(token: str) -> str:
    """SHA-256 hex digest of a token, for safe storage in the sessions table."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
