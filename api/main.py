"""FastAPI service: Paystack webhooks and future API endpoints.

Run locally with:  .venv/bin/uvicorn api.main:app --reload --port 8000

In production this becomes a second component on DO App Platform behind
the /api/* route.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Header, HTTPException, Request

from api.paystack.events import process_event
from api.paystack.signature import verify_signature
from app.db import SessionLocal

log = logging.getLogger("paystack.webhook")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

app = FastAPI(title="Numquants Backend", version="0.1.0")


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

    log.info("event=%s — dispatching", event)

    with SessionLocal() as db:
        handled = process_event(db, event, payload)

    log.info("event=%s handled=%s", event, handled)
    return {"status": "ok", "handled": handled}
