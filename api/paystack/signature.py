"""HMAC-SHA512 signature verification for Paystack webhooks.

Paystack signs every webhook with HMAC-SHA512 using the secret key,
delivered in the `x-paystack-signature` header. We must verify against
the *raw* request body — re-serialising will not match.
"""
from __future__ import annotations

import hashlib
import hmac
import os


def _secret() -> str:
    # Read at call time so tests can monkey-patch the env var.
    return os.environ.get("PAYSTACK_SECRET_KEY", "")


def verify_signature(raw_body: bytes, signature_header: str | None) -> bool:
    secret = _secret()
    if not signature_header or not secret:
        return False
    computed = hmac.new(
        key=secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha512,
    ).hexdigest()
    return hmac.compare_digest(computed, signature_header)


def compute_signature(raw_body: bytes) -> str:
    """Compute the expected signature for `raw_body`. Useful for testing."""
    secret = _secret()
    if not secret:
        raise RuntimeError("PAYSTACK_SECRET_KEY is not set")
    return hmac.new(
        key=secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha512,
    ).hexdigest()
