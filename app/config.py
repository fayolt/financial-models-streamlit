"""Centralised environment configuration.

Reads all env vars once at import time but does NOT raise on missing values.
Each service entrypoint (Streamlit web, FastAPI api) calls the matching
`validate_for_*` function to fail fast on its required vars. This keeps the
two services free to declare only the secrets each actually needs.

The goal is to make a misconfigured deploy fail loud at boot instead of
silently degrading to a known-broken state (e.g. JWT signing with the
dev placeholder secret).
"""
from __future__ import annotations

import logging
import os


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


APP_ENV: str = os.environ.get("APP_ENV", "development").lower()
IS_PRODUCTION: bool = APP_ENV in {"staging", "production"}

_DEV_PLACEHOLDERS: dict[str, str] = {
    "JWT_SECRET": "dev-secret-CHANGE-ME-in-production-must-exceed-32-bytes",
    "DATABASE_URL": "postgresql+psycopg2://numquants:numquants_dev@localhost:5433/numquants",
}


def _read(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


# ── Values (with dev fallbacks). Validation is deferred. ─────────────────────
DATABASE_URL: str = _read(
    "DATABASE_URL",
    "postgresql+psycopg2://numquants:numquants_dev@localhost:5433/numquants",
)
JWT_SECRET: str = _read(
    "JWT_SECRET",
    "dev-secret-CHANGE-ME-in-production-must-exceed-32-bytes",
)
JWT_ALGORITHM: str = _read("JWT_ALGORITHM", "HS256")
SESSION_TTL_SECONDS: int = int(_read("SESSION_TTL_SECONDS", str(30 * 24 * 3600)))

PAYSTACK_SECRET_KEY: str = _read("PAYSTACK_SECRET_KEY")
PAYSTACK_PUBLIC_KEY: str = _read("PAYSTACK_PUBLIC_KEY")
PAYSTACK_BASE_URL: str = _read("PAYSTACK_BASE_URL", "https://api.paystack.co").rstrip("/")

APP_BASE_URL: str = _read("APP_BASE_URL", "http://localhost:8501").rstrip("/")
PAYSTACK_CALLBACK_URL: str = _read("PAYSTACK_CALLBACK_URL", APP_BASE_URL + "/account")

LLM_PROVIDER: str = _read("LLM_PROVIDER", "openai").strip().lower()
OPENAI_API_KEY: str = _read("OPENAI_API_KEY")
OPENAI_MODEL: str = _read("OPENAI_MODEL", "gpt-4o-mini")
ANTHROPIC_API_KEY: str = _read("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL: str = _read("ANTHROPIC_MODEL", "claude-sonnet-4-6")

MAILGUN_API_KEY: str = _read("MAILGUN_API_KEY")
MAILGUN_DOMAIN: str = _read("MAILGUN_DOMAIN", "numquants.com")
MAILGUN_API_BASE: str = _read("MAILGUN_API_BASE", "https://api.mailgun.net").rstrip("/")
MAIL_FROM: str = _read("MAIL_FROM", "")


# ── Per-service requirements ─────────────────────────────────────────────────
_WEB_REQUIRED: list[str] = [
    "DATABASE_URL",
    "JWT_SECRET",
    "PAYSTACK_SECRET_KEY",
    "PAYSTACK_PUBLIC_KEY",
    "APP_BASE_URL",
    "MAILGUN_API_KEY",
]
_API_REQUIRED: list[str] = [
    "DATABASE_URL",
    "PAYSTACK_SECRET_KEY",
]


def _validate(required: list[str], service: str) -> None:
    if not IS_PRODUCTION:
        return
    errors: list[str] = []
    for name in required:
        value = os.environ.get(name, "").strip()
        if not value:
            errors.append(f"{name} is required but empty")
        elif value == _DEV_PLACEHOLDERS.get(name):
            errors.append(f"{name} is set to its dev placeholder value")
    if errors:
        raise ConfigError(
            f"[{service}] startup blocked — APP_ENV={APP_ENV!r}: "
            + "; ".join(errors)
        )


def validate_for_web() -> None:
    """Called by the Streamlit entrypoint."""
    _validate(_WEB_REQUIRED, "web")


def validate_for_api() -> None:
    """Called by the FastAPI entrypoint."""
    _validate(_API_REQUIRED, "api")


def _mask(value: str) -> str:
    if not value:
        return "<unset>"
    if len(value) <= 6:
        return "***"
    return value[:4] + "***" + value[-2:]


def log_startup_summary(service: str) -> None:
    """Emit a single line summarising the loaded config (secrets masked)."""
    log = logging.getLogger(__name__)
    log.info(
        "[%s] config loaded: APP_ENV=%s DATABASE_URL=%s JWT_SECRET=%s "
        "PAYSTACK_SECRET_KEY=%s APP_BASE_URL=%s",
        service,
        APP_ENV,
        _mask(DATABASE_URL),
        _mask(JWT_SECRET),
        _mask(PAYSTACK_SECRET_KEY),
        APP_BASE_URL,
    )
