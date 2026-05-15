"""Unit tests for Paystack webhook signature verification."""
from __future__ import annotations

import hashlib
import hmac

import pytest

from api.paystack import signature as sig_mod


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PAYSTACK_SECRET_KEY", "sk_test_unit_only")


def _sign(body: bytes, secret: str = "sk_test_unit_only") -> str:
    return hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()


def test_verify_signature_correct():
    body = b'{"event":"subscription.create"}'
    assert sig_mod.verify_signature(body, _sign(body))


def test_verify_signature_wrong():
    body = b'{"event":"subscription.create"}'
    assert not sig_mod.verify_signature(body, _sign(b"different body"))


def test_verify_signature_missing_header():
    body = b'{"event":"subscription.create"}'
    assert not sig_mod.verify_signature(body, None)
    assert not sig_mod.verify_signature(body, "")


def test_verify_signature_no_secret(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PAYSTACK_SECRET_KEY", "")
    body = b'{"event":"subscription.create"}'
    assert not sig_mod.verify_signature(body, _sign(body, secret=""))


def test_compute_signature_matches_verify():
    body = b'{"event":"x"}'
    computed = sig_mod.compute_signature(body)
    assert sig_mod.verify_signature(body, computed)
