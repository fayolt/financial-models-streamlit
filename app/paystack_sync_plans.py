"""Pull plans from the Paystack dashboard and save their plan_code into our DB.

Matches by **plan name** (case-insensitive). Skips DB plans on the Free tier
since Paystack doesn't host free plans.

Run with:  .venv/bin/python -m app.paystack_sync_plans
"""
from __future__ import annotations

import os
import sys
from typing import Any

import httpx

from app.db import SessionLocal
from app.db.models import Plan


def _list_paystack_plans() -> list[dict[str, Any]]:
    secret = os.environ.get("PAYSTACK_SECRET_KEY", "")
    if not secret:
        raise RuntimeError("PAYSTACK_SECRET_KEY is not set")
    base = os.environ.get("PAYSTACK_BASE_URL", "https://api.paystack.co").rstrip("/")
    with httpx.Client(timeout=10.0) as c:
        resp = c.get(f"{base}/plan?perPage=100", headers={"Authorization": f"Bearer {secret}"})
    resp.raise_for_status()
    body = resp.json()
    if not body.get("status"):
        raise RuntimeError(body.get("message", "unknown error"))
    return body.get("data") or []


def main() -> int:
    try:
        paystack_plans = _list_paystack_plans()
    except Exception as e:
        print(f"✗ {e}")
        return 1

    by_name = {(p.get("name") or "").strip().lower(): p for p in paystack_plans}

    updated = 0
    skipped: list[str] = []
    with SessionLocal() as db:
        for db_plan in db.query(Plan).all():
            if db_plan.tier == "free":
                continue
            match = by_name.get(db_plan.name.strip().lower())
            if match is None:
                skipped.append(db_plan.name)
                continue
            new_code = match.get("plan_code")
            if not new_code:
                skipped.append(db_plan.name)
                continue
            if db_plan.paystack_plan_code == new_code:
                print(f"= {db_plan.name}: already up to date ({new_code})")
                continue
            db_plan.paystack_plan_code = new_code
            updated += 1
            print(f"✓ {db_plan.name}: paystack_plan_code = {new_code}")
        db.commit()

    if skipped:
        print()
        print("! Not found in Paystack (create them in dashboard.paystack.com → Plans):")
        for name in skipped:
            print(f"  - {name}")

    print()
    print(f"{updated} plan(s) updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
