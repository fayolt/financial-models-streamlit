"""Seed the default Free / Pro / Enterprise plans.

Run with: `.venv/bin/python -m app.db.seed`

Idempotent: if a plan already exists by slug, its fields are updated
in-place. paystack_plan_code starts NULL; populate it in production
after creating the plan in the Paystack dashboard.
"""
from __future__ import annotations

from app.db import SessionLocal
from app.db.models import Plan

DEFAULT_PLANS: list[dict] = [
    {
        "slug": "free",
        "name": "Free",
        "tier": "free",
        "paystack_plan_code": None,
        "monthly_price_minor_units": 0,
        "currency": "ZAR",
        "monthly_report_quota": 0,  # on-screen only, no exports
    },
    {
        "slug": "pro",
        "name": "Pro",
        "tier": "pro",
        "paystack_plan_code": None,
        # Matches the ZAR plan already configured in the Paystack dashboard.
        # If you change this, also update the amount in dashboard.paystack.com.
        "monthly_price_minor_units": 250 * 100,  # ZAR 250.00 in cents
        "currency": "ZAR",
        "monthly_report_quota": 50,
    },
    {
        "slug": "enterprise",
        "name": "Enterprise",
        "tier": "enterprise",
        "paystack_plan_code": None,
        "monthly_price_minor_units": 300 * 100,  # ZAR 300.00
        "currency": "ZAR",
        "monthly_report_quota": None,  # unlimited
    },
]


def seed_plans() -> None:
    with SessionLocal() as db:
        for spec in DEFAULT_PLANS:
            existing = db.query(Plan).filter_by(slug=spec["slug"]).first()
            if existing is None:
                db.add(Plan(**spec))
                print(f"created plan: {spec['slug']}")
            else:
                for key, value in spec.items():
                    if key == "paystack_plan_code" and existing.paystack_plan_code:
                        continue  # never clobber a real plan code
                    setattr(existing, key, value)
                print(f"updated plan: {spec['slug']}")
        db.commit()


if __name__ == "__main__":
    seed_plans()
