"""FastAPI service: Paystack webhooks and future API endpoints.

Run locally with:  .venv/bin/uvicorn api.main:app --reload --port 8000

In production this becomes a second component on DO App Platform behind
the /api/* route.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException, Request

from app.config import APP_ENV, log_startup_summary, validate_for_api
from app.logging_setup import configure_logging

# JSON logs to stdout for DO/Datadog ingestion.
configure_logging("api")

# Fail loud on missing/placeholder secrets in production.
validate_for_api()

from api.paystack.events import process_event
from api.paystack.signature import verify_signature
from app.db import SessionLocal
from app.db.models import WebhookEvent

log = logging.getLogger("paystack.webhook")
log_startup_summary("api")

app = FastAPI(
    title="Numquants Backend",
    version="0.1.0",
    # Disable docs in production to avoid exposing API schema publicly.
    docs_url=None if APP_ENV == "production" else "/docs",
    redoc_url=None if APP_ENV == "production" else "/redoc",
)

# Optional Datadog APM — activate when ddtrace is installed and DD_API_KEY is set.
import os as _os  # noqa: E402

if _os.environ.get("DD_API_KEY"):
    try:
        from ddtrace.contrib.asgi import TraceMiddleware  # type: ignore[import]
        from ddtrace import tracer as _dd_tracer  # type: ignore[import]
        app.add_middleware(TraceMiddleware, tracer=_dd_tracer)
        log.info("Datadog APM tracing enabled")
    except ImportError:
        log.info("ddtrace not installed — APM tracing disabled")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/webhooks/paystack")
async def paystack_webhook(
    request: Request,
    x_paystack_signature: str | None = Header(default=None),
) -> dict[str, str | bool]:
    raw_body = await request.body()

    # Always log arrival so we can see whether Paystack is even reaching us.
    log.info(
        "incoming webhook (%d bytes, sig=%s, ip=%s)",
        len(raw_body),
        "present" if x_paystack_signature else "MISSING",
        request.client.host if request.client else "?",
    )

    if not verify_signature(raw_body, x_paystack_signature):
        log.warning("signature verification FAILED — rejecting")
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = await request.json()
    except Exception as e:
        log.warning("invalid JSON body: %s", e)
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

    event = payload.get("event")
    if not event:
        log.warning("payload missing 'event' field")
        raise HTTPException(status_code=400, detail="Missing 'event' field")

    # Idempotency: dedup by SHA-256 of the raw body. Paystack retries deliver
    # the same body, so identical hash means we've already seen this event.
    event_id = hashlib.sha256(raw_body).hexdigest()

    with SessionLocal() as db:
        existing = (
            db.query(WebhookEvent)
            .filter(WebhookEvent.event_id == event_id)
            .one_or_none()
        )
        if existing is not None:
            log.info(
                "event=%s duplicate (event_id=%s prior status=%s) — skipping",
                event,
                event_id[:12],
                existing.status,
            )
            return {"status": "ok", "handled": False, "deduped": True}

        record = WebhookEvent(
            provider="paystack",
            event_id=event_id,
            event_type=event,
            status="received",
            raw_payload=payload,
        )
        db.add(record)
        db.commit()

        log.info("event=%s id=%s — dispatching", event, event_id[:12])
        try:
            handled = process_event(db, event, payload)
            record.status = "processed"
            record.processed_at = datetime.now(timezone.utc)
            db.commit()
        except Exception as e:
            log.exception("event=%s handler failed", event)
            record.status = "failed"
            record.error_message = str(e)[:1000]
            db.commit()
            raise HTTPException(status_code=500, detail="Handler failed")

    log.info("event=%s handled=%s", event, handled)
    return {"status": "ok", "handled": handled}
