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


def fetch_subscription(subscription_code: str) -> dict[str, Any]:
    """Fetch a subscription by its code. Includes the email_token needed to disable."""
    with httpx.Client(timeout=10.0) as c:
        resp = c.get(
            f"{_base_url()}/subscription/{subscription_code}", headers=_headers()
        )
    return _unwrap(resp)


def disable_subscription(subscription_code: str) -> dict[str, Any]:
    """Cancel a Paystack subscription. Idempotent: succeeds if already disabled."""
    detail = fetch_subscription(subscription_code)
    email_token = detail.get("email_token")
    if not email_token:
        raise PaystackError("Subscription has no email_token; cannot disable.")
    with httpx.Client(timeout=10.0) as c:
        resp = c.post(
            f"{_base_url()}/subscription/disable",
            headers=_headers(),
            json={"code": subscription_code, "token": email_token},
        )
    return _unwrap(resp)


def issue_refund(
    *,
    transaction_reference: str,
    amount_minor_units: int | None = None,
    currency: str | None = None,
    merchant_note: str | None = None,
) -> dict[str, Any]:
    """Refund a charge by transaction reference.

    `amount_minor_units` is in the smallest currency unit (cents for ZAR).
    Omit it for a full refund. Returns Paystack's refund record including the
    refund id used to correlate webhook events.
    """
    body: dict[str, Any] = {"transaction": transaction_reference}
    if amount_minor_units is not None:
        body["amount"] = amount_minor_units
    if currency:
        body["currency"] = currency
    if merchant_note:
        body["merchant_note"] = merchant_note
    with httpx.Client(timeout=15.0) as c:
        resp = c.post(f"{_base_url()}/refund", headers=_headers(), json=body)
    return _unwrap(resp)
