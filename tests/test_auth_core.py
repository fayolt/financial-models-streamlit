"""Unit tests for password hashing and JWT session tokens."""
from __future__ import annotations

from uuid import uuid4

import pytest

from app.auth import (
    InvalidTokenError,
    hash_password,
    issue_session_token,
    needs_rehash,
    token_hash,
    verify_password,
    verify_session_token,
)


# --- password hashing ----------------------------------------------------------


def test_hash_verify_roundtrip():
    h = hash_password("Sw0rdfish!")
    assert h.startswith("$argon2")
    assert verify_password(h, "Sw0rdfish!")


def test_verify_rejects_wrong_password():
    h = hash_password("correct horse battery staple")
    assert not verify_password(h, "wrong horse battery staple")


def test_hash_is_salted():
    a = hash_password("samepwd")
    b = hash_password("samepwd")
    assert a != b


def test_verify_handles_garbage_hash():
    assert not verify_password("not-a-real-hash", "anything")


def test_needs_rehash_on_fresh_hash_is_false():
    assert not needs_rehash(hash_password("x"))


# --- JWT session tokens --------------------------------------------------------


def test_token_roundtrip():
    user_id = uuid4()
    token, expires_at = issue_session_token(user_id=user_id, email="x@y.com")
    payload = verify_session_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["email"] == "x@y.com"
    assert payload["exp"] == int(expires_at.timestamp())


def test_token_expired_rejected():
    token, _ = issue_session_token(
        user_id=uuid4(), email="x@y.com", ttl_seconds=-1
    )
    with pytest.raises(InvalidTokenError):
        verify_session_token(token)


def test_token_tampered_rejected():
    token, _ = issue_session_token(user_id=uuid4(), email="x@y.com")
    tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
    with pytest.raises(InvalidTokenError):
        verify_session_token(tampered)


def test_token_hash_is_deterministic():
    a, _ = issue_session_token(user_id=uuid4(), email="x@y.com")
    assert token_hash(a) == token_hash(a)
    assert len(token_hash(a)) == 64  # sha256 hex
