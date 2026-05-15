"""Minimal Paystack REST API client (sync, httpx)."""
from __future__ import annotations

import os
from typing import Any

import httpx


class PaystackError(RuntimeError):
    pass


def _base_url() -> str:
    return os.environ.get("PAYSTACK_BASE_URL", "https://api.paystack.co").rstrip("/")


def _headers() -> dict[str, str]:
    secret = os.environ.get("PAYSTACK_SECRET_KEY", "")
    if not secret:
        raise PaystackError("PAYSTACK_SECRET_KEY is not set")
    return {
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/json",
    }


def _unwrap(resp: httpx.Response) -> dict[str, Any]:
    if resp.status_code >= 400:
        raise PaystackError(f"Paystack HTTP {resp.status_code}: {resp.text}")
    body = resp.json()
    if not body.get("status"):
        raise PaystackError(f"Paystack error: {body.get('message')}")
    return body.get("data", {})


def initialize_transaction(
    *,
    email: str,
    amount_kobo: int,
    plan_code: str | None = None,
    callback_url: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Initialise a transaction. Returns {authorization_url, access_code, reference}."""
    body: dict[str, Any] = {"email": email, "amount": amount_kobo}
    if plan_code:
        body["plan"] = plan_code
    if callback_url:
        body["callback_url"] = callback_url
    if metadata:
        body["metadata"] = metadata
    with httpx.Client(timeout=10.0) as c:
        resp = c.post(f"{_base_url()}/transaction/initialize", headers=_headers(), json=body)
    return _unwrap(resp)


def verify_transaction(reference: str) -> dict[str, Any]:
    """Verify a transaction by reference. Returns full transaction details."""
    with httpx.Client(timeout=10.0) as c:
        resp = c.get(f"{_base_url()}/transaction/verify/{reference}", headers=_headers())
    return _unwrap(resp)


def fetch_plan(plan_code: str) -> dict[str, Any]:
    with httpx.Client(timeout=10.0) as c:
        resp = c.get(f"{_base_url()}/plan/{plan_code}", headers=_headers())
    return _unwrap(resp)
