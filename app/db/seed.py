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
        "currency": "NGN",
        "monthly_report_quota": 0,  # on-screen only, no exports
    },
    {
        "slug": "pro",
        "name": "Pro",
        "tier": "pro",
        "paystack_plan_code": None,
        "monthly_price_minor_units": 15_000 * 100,  # ₦15,000 in kobo
        "currency": "NGN",
        "monthly_report_quota": 50,
    },
    {
        "slug": "enterprise",
        "name": "Enterprise",
        "tier": "enterprise",
        "paystack_plan_code": None,
        "monthly_price_minor_units": 50_000 * 100,  # ₦50,000
        "currency": "NGN",
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
