"""Signup, login, logout, current-user resolution, and password-reset flow."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session as SASession

from app.auth.passwords import hash_password, needs_rehash, verify_password
from app.auth.tokens import (
    EMAIL_VERIFY_TTL_SECONDS,
    PASSWORD_RESET_TTL_SECONDS,
    InvalidTokenError,
    issue_email_verify_token,
    issue_reset_token,
    issue_session_token,
    token_hash,
    verify_email_verify_token,
    verify_reset_token,
    verify_session_token,
)
from app.db.models import Session as SessionRow, User
from app.email import (
    account_deleted_email,
    password_changed_email,
    password_reset_email,
    send_email_best_effort,
    signup_attempt_existing_email,
    verify_email_email,
    welcome_email,
)


class AuthError(ValueError):
    """User-facing auth error (bad credentials, email taken, etc.)."""


MIN_PASSWORD_LENGTH = 8


class SignupAlreadyExists(Exception):
    """Internal signal: signup tried to create an account with a taken email.
    Not raised to the UI — see `signup_silent()`."""


def signup(
    db: SASession,
    *,
    email: str,
    password: str,
    full_name: str | None = None,
) -> User:
    email = email.strip().lower()
    if "@" not in email:
        raise AuthError("Please enter a valid email address.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    existing = db.query(User).filter_by(email=email).first()
    if existing is not None:
        raise SignupAlreadyExists()
    user = User(
        email=email,
        password_hash=hash_password(password),
        full_name=full_name.strip() if full_name else None,
        tier="free",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    _send_welcome_email(user)
    _send_verify_email(user)
    return user


def _send_verify_email(user: User) -> None:
    token, _ = issue_email_verify_token(user_id=user.id)
    verify_link = f"{_app_base_url()}/?verify_email_token={token}"
    subject, text, html = verify_email_email(
        recipient_email=user.email,
        verify_link=verify_link,
        ttl_hours=EMAIL_VERIFY_TTL_SECONDS // 3600,
    )
    send_email_best_effort(to=user.email, subject=subject, text=text, html=html)


def request_email_verification(db: SASession, *, user_id: UUID) -> bool:
    """Re-send the verification email to a user who's still unverified."""
    user = db.get(User, user_id)
    if user is None or user.email_verified_at is not None:
        return False
    _send_verify_email(user)
    return True


def confirm_email_verification(db: SASession, *, token: str) -> User:
    """Verify the email-verification JWT and mark the user verified.
    Idempotent — re-clicking the link keeps the original `email_verified_at`."""
    try:
        user_id = verify_email_verify_token(token)
    except InvalidTokenError as e:
        raise AuthError(f"Verification link is invalid or expired: {e}") from e
    user = db.get(User, user_id)
    if user is None:
        raise AuthError("Account not found.")
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(user)
    return user


def signup_silent(
    db: SASession,
    *,
    email: str,
    password: str,
    full_name: str | None = None,
) -> User | None:
    """Like signup(), but if the email is already registered, returns None
    after sending an "account already exists" email to that address. Used by
    the UI so we never leak which addresses are on file."""
    try:
        return signup(db, email=email, password=password, full_name=full_name)
    except SignupAlreadyExists:
        normalized = email.strip().lower()
        subject, text, html = signup_attempt_existing_email(
            recipient_email=normalized,
            app_url=_app_base_url(),
        )
        send_email_best_effort(
            to=normalized, subject=subject, text=text, html=html
        )
        return None


def _app_base_url() -> str:
    from app.config import APP_BASE_URL
    return APP_BASE_URL


def _send_welcome_email(user: User) -> None:
    subject, text, html = welcome_email(
        recipient_email=user.email,
        full_name=user.full_name,
        app_url=_app_base_url(),
    )
    send_email_best_effort(to=user.email, subject=subject, text=text, html=html)


def request_password_reset(db: SASession, *, email: str) -> bool:
    """Send a password-reset email if the address exists. Always returns True
    to the caller — we don't disclose whether an email is registered."""
    email = email.strip().lower()
    user = db.query(User).filter_by(email=email).first()
    if user is None or not user.is_active:
        return True  # silent for security
    token, _ = issue_reset_token(user_id=user.id)
    reset_link = f"{_app_base_url()}/?reset_token={token}"
    subject, text, html = password_reset_email(
        recipient_email=user.email,
        reset_link=reset_link,
        ttl_minutes=PASSWORD_RESET_TTL_SECONDS // 60,
    )
    send_email_best_effort(to=user.email, subject=subject, text=text, html=html)
    return True


def change_password(
    db: SASession,
    *,
    user_id: UUID,
    current_password: str,
    new_password: str,
    keep_current_session_token: str | None = None,
) -> User:
    """Verify the user's current password, set a new one, revoke other sessions.

    If `keep_current_session_token` is provided, that one session is preserved
    so the user isn't logged out of the tab where they just changed their
    password. All other sessions are revoked for safety."""
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthError("User not found.")
    if not verify_password(user.password_hash, current_password):
        raise AuthError("Current password is incorrect.")
    if len(new_password) < 8:
        raise AuthError("New password must be at least 8 characters.")
    if verify_password(user.password_hash, new_password):
        raise AuthError("New password must differ from the current one.")

    user.password_hash = hash_password(new_password)
    now = datetime.now(timezone.utc)
    revoke_query = (
        db.query(SessionRow)
        .filter_by(user_id=user.id)
        .filter(SessionRow.revoked_at.is_(None))
    )
    if keep_current_session_token:
        revoke_query = revoke_query.filter(
            SessionRow.token_hash != token_hash(keep_current_session_token)
        )
    revoke_query.update(
        {SessionRow.revoked_at: now}, synchronize_session=False
    )
    db.commit()

    subject, text, html = password_changed_email(recipient_email=user.email)
    send_email_best_effort(to=user.email, subject=subject, text=text, html=html)
    return user


def update_profile(
    db: SASession, *, user_id: UUID, full_name: str | None
) -> User:
    """Update the user's profile fields. Currently only full_name."""
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthError("User not found.")
    if full_name is None:
        # Nothing to do — surface as a no-op rather than error.
        return user
    user.full_name = full_name.strip() or None
    db.commit()
    return user


def delete_account(
    db: SASession, *, user_id: UUID, password_confirm: str
) -> str:
    """Delete the user after verifying their password. Returns the email
    address (for caller-side cookie clearing / messaging).

    Tries to cancel any active Paystack subscriptions first, best-effort —
    a failed Paystack call doesn't block deletion (user wants out)."""
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthError("User not found.")
    if not verify_password(user.password_hash, password_confirm):
        raise AuthError("Password is incorrect.")

    email = user.email

    # Best-effort: cancel active Paystack subscriptions before deleting the user.
    from app.db.models import Subscription
    try:
        from api.paystack import disable_subscription
    except Exception:  # pragma: no cover — defensive
        disable_subscription = None  # type: ignore[assignment]

    active_subs = (
        db.query(Subscription)
        .filter_by(user_id=user.id)
        .filter(Subscription.status.in_(("active", "past_due")))
        .all()
    )
    for sub in active_subs:
        if disable_subscription and sub.paystack_subscription_code:
            try:
                disable_subscription(sub.paystack_subscription_code)
            except Exception:
                pass  # carry on with deletion

    # CASCADE wipes sessions, subscriptions, report_runs.
    db.delete(user)
    db.commit()

    subject, text, html = account_deleted_email(recipient_email=email)
    send_email_best_effort(to=email, subject=subject, text=text, html=html)
    return email


def complete_password_reset(
    db: SASession, *, token: str, new_password: str
) -> User:
    """Verify a reset token, set the new password, revoke existing sessions."""
    try:
        user_id = verify_reset_token(token)
    except InvalidTokenError as e:
        raise AuthError(f"Reset link is invalid or expired: {e}")
    if len(new_password) < 8:
        raise AuthError("Password must be at least 8 characters.")
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthError("Reset link is invalid or expired.")
    user.password_hash = hash_password(new_password)
    # Revoke all existing sessions for safety — the attacker (if any) is logged out.
    now = datetime.now(timezone.utc)
    (
        db.query(SessionRow)
        .filter_by(user_id=user.id)
        .filter(SessionRow.revoked_at.is_(None))
        .update({SessionRow.revoked_at: now}, synchronize_session=False)
    )
    db.commit()
    return user


def login(
    db: SASession,
    *,
    email: str,
    password: str,
    user_agent: str | None = None,
) -> tuple[User, str]:
    """Validate credentials, persist a session row, return (user, JWT)."""
    email = email.strip().lower()
    user = db.query(User).filter_by(email=email).first()
    if user is None or not user.is_active:
        raise AuthError("Invalid credentials.")
    if not verify_password(user.password_hash, password):
        raise AuthError("Invalid credentials.")
    # Opportunistic rehash if argon2 parameters have changed since signup.
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    token, expires_at = issue_session_token(user_id=user.id, email=user.email)
    session_row = SessionRow(
        user_id=user.id,
        token_hash=token_hash(token),
        expires_at=expires_at,
        user_agent=user_agent,
    )
    db.add(session_row)
    db.commit()
    return user, token


def logout(db: SASession, token: str | None) -> None:
    """Revoke the session for a token. Silent if the token is unknown."""
    if not token:
        return
    row = db.query(SessionRow).filter_by(token_hash=token_hash(token)).first()
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        db.commit()


def get_current_user(db: SASession, token: str | None) -> Optional[User]:
    """Resolve a session JWT to a User, returning None if missing/invalid."""
    if not token:
        return None
    try:
        payload = verify_session_token(token)
    except InvalidTokenError:
        return None
    row = db.query(SessionRow).filter_by(token_hash=token_hash(token)).first()
    if row is None or row.revoked_at is not None:
        return None
    if row.expires_at < datetime.now(timezone.utc):
        return None
    user = db.get(User, UUID(payload["sub"]))
    if user is None or not user.is_active:
        return None
    return user
