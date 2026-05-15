"""FastAPI service: Paystack webhooks and future API endpoints.

Run locally with:  .venv/bin/uvicorn api.main:app --reload --port 8000

In production this becomes a second component on DO App Platform behind
the /api/* route.
"""
from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException, Request

from api.paystack.events import process_event
from api.paystack.signature import verify_signature
from app.db import SessionLocal

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
    if not verify_signature(raw_body, x_paystack_signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

    event = payload.get("event")
    if not event:
        raise HTTPException(status_code=400, detail="Missing 'event' field")

    with SessionLocal() as db:
        handled = process_event(db, event, payload)

    return {"status": "ok", "handled": handled}
