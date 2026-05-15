"""Mailgun client. Sync HTTP via httpx. All env vars read at call time."""
from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger(__name__)


class EmailError(RuntimeError):
    """Raised when an email cannot be sent."""


def _config() -> tuple[str, str, str, str]:
    """Returns (api_key, domain, base_url, sender) or raises EmailError if missing."""
    api_key = os.environ.get("MAILGUN_API_KEY", "")
    domain = os.environ.get("MAILGUN_DOMAIN", "")
    base_url = os.environ.get("MAILGUN_API_BASE", "https://api.mailgun.net").rstrip("/")
    sender = os.environ.get("MAIL_FROM", "")
    if not (api_key and domain and sender):
        raise EmailError(
            "Mailgun not configured (need MAILGUN_API_KEY, MAILGUN_DOMAIN, MAIL_FROM)"
        )
    return api_key, domain, base_url, sender


def send_email(
    *,
    to: str,
    subject: str,
    text: str,
    html: str | None = None,
) -> None:
    """Send a transactional email via Mailgun. Raises EmailError on failure."""
    api_key, domain, base_url, sender = _config()

    payload = {"from": sender, "to": to, "subject": subject, "text": text}
    if html:
        payload["html"] = html

    try:
        with httpx.Client(timeout=10.0) as c:
            resp = c.post(
                f"{base_url}/v3/{domain}/messages",
                auth=("api", api_key),
                data=payload,
            )
    except EmailError:
        raise
    except Exception as e:
        raise EmailError(f"Mailgun call failed: {e}") from e

    if resp.status_code >= 400:
        raise EmailError(f"Mailgun HTTP {resp.status_code}: {resp.text}")


def send_email_best_effort(**kwargs) -> bool:
    """Send and swallow EmailError, logging a warning. Returns True on success.

    Use for non-critical emails (e.g. welcome) where the user action should
    not fail just because the email could not be delivered.
    """
    try:
        send_email(**kwargs)
        return True
    except EmailError as e:
        log.warning("send_email_best_effort failed: %s", e)
        return False
