"""Integration tests for the FastAPI /api/webhooks/paystack endpoint.

Verifies signature gate, event dispatch, and DB side effects against the
live docker-compose Postgres. Skipped if the database is unreachable.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import SessionLocal, engine
from app.db.models import Plan, Subscription, User

_SECRET = "sk_test_webhook_only"


def _has_db() -> bool:
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _has_db(), reason="No Postgres reachable")


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PAYSTACK_SECRET_KEY", _SECRET)


@pytest.fixture
def client() -> TestClient:
    # Import inside the fixture so the env-var fixture runs first.
    from api.main import app
    return TestClient(app)


@pytest.fixture
def fixtures():
    """Create a test user + pro plan; clean them up afterwards."""
    user_email = f"webhook_{uuid.uuid4().hex[:8]}@example.com"
    customer_code = f"CUS_{uuid.uuid4().hex[:10]}"
    plan_code = f"PLN_{uuid.uuid4().hex[:10]}"
    sub_code = f"SUB_{uuid.uuid4().hex[:10]}"

    with SessionLocal() as db:
        user = User(
            email=user_email,
            password_hash="$argon2id$placeholder",
            tier="free",
            paystack_customer_id=customer_code,
        )
        plan = Plan(
            slug=f"pro-{uuid.uuid4().hex[:6]}",
            name="Pro",
            tier="pro",
            paystack_plan_code=plan_code,
            monthly_price_minor_units=1_500_000,
            currency="NGN",
        )
        db.add_all([user, plan])
        db.commit()
        user_id, plan_id = user.id, plan.id

    yield {
        "user_email": user_email,
        "customer_code": customer_code,
        "plan_code": plan_code,
        "sub_code": sub_code,
        "user_id": user_id,
        "plan_id": plan_id,
    }

    with SessionLocal() as db:
        db.query(Subscription).filter_by(paystack_subscription_code=sub_code).delete()
        db.query(User).filter_by(id=user_id).delete()
        db.query(Plan).filter_by(id=plan_id).delete()
        db.commit()


def _sign(body: bytes) -> str:
    return hmac.new(_SECRET.encode(), body, hashlib.sha512).hexdigest()


def _post(client: TestClient, payload: dict, *, sign: bool = True) -> object:
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if sign:
        headers["x-paystack-signature"] = _sign(body)
    return client.post("/api/webhooks/paystack", content=body, headers=headers)


# --- routing & auth ----------------------------------------------------------


def test_health(client: TestClient):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_unsigned_rejected(client: TestClient):
    resp = _post(client, {"event": "subscription.create", "data": {}}, sign=False)
    assert resp.status_code == 401


def test_wrong_signature_rejected(client: TestClient):
    body = json.dumps({"event": "x"}).encode()
    resp = client.post(
        "/api/webhooks/paystack",
        content=body,
        headers={"x-paystack-signature": "bad", "Content-Type": "application/json"},
    )
    assert resp.status_code == 401


def test_unknown_event_acked_not_handled(client: TestClient):
    resp = _post(client, {"event": "totally.made.up", "data": {}})
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "handled": False}


# --- subscription.create -----------------------------------------------------


def test_subscription_create_activates_user(client: TestClient, fixtures):
    payload = {
        "event": "subscription.create",
        "data": {
            "subscription_code": fixtures["sub_code"],
            "customer": {
                "email": fixtures["user_email"],
                "customer_code": fixtures["customer_code"],
            },
            "plan": {"plan_code": fixtures["plan_code"]},
        },
    }
    resp = _post(client, payload)
    assert resp.status_code == 200
    assert resp.json()["handled"] is True

    with SessionLocal() as db:
        user = db.get(User, fixtures["user_id"])
        assert user.tier == "pro"
        sub = db.query(Subscription).filter_by(
            paystack_subscription_code=fixtures["sub_code"]
        ).first()
        assert sub is not None
        assert sub.status == "active"


def test_subscription_create_is_idempotent(client: TestClient, fixtures):
    payload = {
        "event": "subscription.create",
        "data": {
            "subscription_code": fixtures["sub_code"],
            "customer": {
                "email": fixtures["user_email"],
                "customer_code": fixtures["customer_code"],
            },
            "plan": {"plan_code": fixtures["plan_code"]},
        },
    }
    _post(client, payload)
    _post(client, payload)  # second delivery — should not create a duplicate row
    with SessionLocal() as db:
        rows = db.query(Subscription).filter_by(
            paystack_subscription_code=fixtures["sub_code"]
        ).all()
        assert len(rows) == 1


# --- subscription.disable ----------------------------------------------------


def test_subscription_disable_demotes_user(client: TestClient, fixtures):
    # First activate.
    _post(client, {
        "event": "subscription.create",
        "data": {
            "subscription_code": fixtures["sub_code"],
            "customer": {
                "email": fixtures["user_email"],
                "customer_code": fixtures["customer_code"],
            },
            "plan": {"plan_code": fixtures["plan_code"]},
        },
    })
    # Then cancel.
    resp = _post(client, {
        "event": "subscription.disable",
        "data": {"subscription_code": fixtures["sub_code"]},
    })
    assert resp.status_code == 200

    with SessionLocal() as db:
        user = db.get(User, fixtures["user_id"])
        assert user.tier == "free"
        sub = db.query(Subscription).filter_by(
            paystack_subscription_code=fixtures["sub_code"]
        ).first()
        assert sub.status == "cancelled"
        assert sub.cancelled_at is not None


# --- invoice.payment_failed --------------------------------------------------


def test_payment_failed_marks_past_due(client: TestClient, fixtures):
    _post(client, {
        "event": "subscription.create",
        "data": {
            "subscription_code": fixtures["sub_code"],
            "customer": {
                "email": fixtures["user_email"],
                "customer_code": fixtures["customer_code"],
            },
            "plan": {"plan_code": fixtures["plan_code"]},
        },
    })
    _post(client, {
        "event": "invoice.payment_failed",
        "data": {"subscription": {"subscription_code": fixtures["sub_code"]}},
    })
    with SessionLocal() as db:
        sub = db.query(Subscription).filter_by(
            paystack_subscription_code=fixtures["sub_code"]
        ).first()
        assert sub.status == "past_due"
