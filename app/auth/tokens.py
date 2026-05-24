"""JWT session token issuing and verification."""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import jwt

from app.config import JWT_ALGORITHM, JWT_SECRET, SESSION_TTL_SECONDS


class InvalidTokenError(Exception):
    """Raised when a JWT fails signature, expiry, or claim validation."""


PASSWORD_RESET_TTL_SECONDS: int = 3600  # 1 hour
EMAIL_VERIFY_TTL_SECONDS: int = 48 * 3600  # 48 hours — let signup emails sit in inbox over the weekend


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
        # `jti` makes every issued token unique even when called twice in the
        # same second — otherwise two rapid logins collide on token_hash.
        "jti": uuid.uuid4().hex,
        "sub": str(user_id),
        "email": email,
        "purpose": "session",
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token, expires_at


def verify_session_token(token: str) -> dict[str, Any]:
    """Decode and validate a session JWT. Raises InvalidTokenError on failure.

    Accepts tokens without a `purpose` claim for backwards compatibility with
    sessions issued before reset-token support landed; rejects tokens whose
    `purpose` is set to anything other than 'session'."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError as e:
        raise InvalidTokenError(str(e)) from e
    purpose = payload.get("purpose", "session")
    if purpose != "session":
        raise InvalidTokenError(f"Token purpose is {purpose!r}, not 'session'")
    return payload


def issue_reset_token(
    *, user_id: UUID, ttl_seconds: int = PASSWORD_RESET_TTL_SECONDS
) -> tuple[str, datetime]:
    """Return (token, expires_at) for a short-lived password-reset JWT."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=ttl_seconds)
    payload = {
        "jti": uuid.uuid4().hex,
        "sub": str(user_id),
        "purpose": "reset",
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token, expires_at


def verify_reset_token(token: str) -> UUID:
    """Validate a password-reset token and return the user_id it identifies.

    Raises InvalidTokenError on signature/expiry failure or wrong purpose."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError as e:
        raise InvalidTokenError(str(e)) from e
    if payload.get("purpose") != "reset":
        raise InvalidTokenError("Token is not a password-reset token")
    try:
        return UUID(payload["sub"])
    except (KeyError, ValueError) as e:
        raise InvalidTokenError(f"Malformed token payload: {e}") from e


def issue_email_verify_token(
    *, user_id: UUID, ttl_seconds: int = EMAIL_VERIFY_TTL_SECONDS
) -> tuple[str, datetime]:
    """Return (token, expires_at) for a short-lived email-verification JWT."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=ttl_seconds)
    payload = {
        "jti": uuid.uuid4().hex,
        "sub": str(user_id),
        "purpose": "verify_email",
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token, expires_at


def verify_email_verify_token(token: str) -> UUID:
    """Validate an email-verification token and return the user_id."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError as e:
        raise InvalidTokenError(str(e)) from e
    if payload.get("purpose") != "verify_email":
        raise InvalidTokenError("Token is not an email-verification token")
    try:
        return UUID(payload["sub"])
    except (KeyError, ValueError) as e:
        raise InvalidTokenError(f"Malformed token payload: {e}") from e


def token_hash(token: str) -> str:
    """SHA-256 hex digest of a token, for safe storage in the sessions table."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
