"""Diagnose Paystack configuration: env vars, API connectivity, plan codes.

Run with:  .venv/bin/python -m app.paystack_check
"""
from __future__ import annotations

import os
import sys
from typing import Any

import httpx

from app.db import SessionLocal
from app.db.models import Plan

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
RESET = "\033[0m"


def _ok(msg: str) -> None:
    print(f"{GREEN}✓{RESET} {msg}")


def _bad(msg: str) -> None:
    print(f"{RED}✗{RESET} {msg}")


def _warn(msg: str) -> None:
    print(f"{YELLOW}!{RESET} {msg}")


def _info(msg: str) -> None:
    print(f"  {DIM}{msg}{RESET}")


def _masked(value: str, keep: int = 8) -> str:
    if len(value) <= keep + 4:
        return value
    return f"{value[:keep]}…{value[-4:]}"


def _list_paystack_plans(secret: str, base_url: str) -> list[dict[str, Any]]:
    headers = {"Authorization": f"Bearer {secret}"}
    with httpx.Client(timeout=10.0) as c:
        resp = c.get(f"{base_url.rstrip('/')}/plan?perPage=100", headers=headers)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text}")
    data = resp.json()
    if not data.get("status"):
        raise RuntimeError(data.get("message", "unknown error"))
    return data.get("data") or []


def main() -> int:
    print()
    print(f"{DIM}Paystack configuration check{RESET}")
    print()

    # --- env vars ----------------------------------------------------------
    secret = os.environ.get("PAYSTACK_SECRET_KEY", "")
    public = os.environ.get("PAYSTACK_PUBLIC_KEY", "")
    base_url = os.environ.get("PAYSTACK_BASE_URL", "https://api.paystack.co")

    problems = 0

    if secret and secret.startswith(("sk_test_", "sk_live_")):
        _ok(f"PAYSTACK_SECRET_KEY set ({_masked(secret)})")
        if secret.startswith("sk_test_"):
            _info("Test mode.")
        else:
            _warn("Live mode — real cards will be charged.")
    else:
        _bad("PAYSTACK_SECRET_KEY missing or malformed (expected sk_test_… or sk_live_…)")
        problems += 1

    if public and public.startswith(("pk_test_", "pk_live_")):
        _ok(f"PAYSTACK_PUBLIC_KEY set ({_masked(public)})")
    else:
        _bad("PAYSTACK_PUBLIC_KEY missing or malformed")
        problems += 1

    _ok(f"PAYSTACK_BASE_URL = {base_url}")
    print()

    # --- API connectivity --------------------------------------------------
    paystack_plans: list[dict[str, Any]] = []
    if secret:
        try:
            paystack_plans = _list_paystack_plans(secret, base_url)
            _ok(f"Paystack API reachable, {len(paystack_plans)} plan(s) in dashboard")
        except Exception as e:
            _bad(f"Paystack API call failed: {e}")
            problems += 1
    print()

    # --- DB plans ----------------------------------------------------------
    print(f"{DIM}Plans in local DB:{RESET}")
    try:
        with SessionLocal() as db:
            db_plans = db.query(Plan).order_by(Plan.tier).all()
    except Exception as e:
        _bad(f"Could not read DB: {e}")
        _info("Is Postgres running?  `make db-up` or `docker-compose up -d db`")
        return 1

    if not db_plans:
        _bad("No plans in DB — run `make seed` or `python -m app.db.seed`")
        problems += 1
        return problems

    for plan in db_plans:
        amount = plan.monthly_price_minor_units / 100
        code = plan.paystack_plan_code or "(none)"
        status = ""
        if plan.tier == "free":
            status = f"{GREEN}OK{RESET} (free tier — no Paystack plan needed)"
        elif plan.paystack_plan_code:
            in_paystack = any(p.get("plan_code") == plan.paystack_plan_code for p in paystack_plans)
            status = f"{GREEN}OK{RESET}" if in_paystack else f"{RED}plan_code not found in Paystack{RESET}"
            if not in_paystack and paystack_plans:
                problems += 1
        else:
            status = f"{YELLOW}MISSING plan_code{RESET}"
            problems += 1
        print(
            f"  {plan.slug:<12} tier={plan.tier:<11} "
            f"{plan.currency} {amount:>8,.2f}  paystack_plan_code={code}  {status}"
        )
    print()

    # --- next-step guidance ------------------------------------------------
    if problems == 0:
        _ok("All checks passed — Paystack is ready to use.")
        return 0

    print(f"{YELLOW}Next steps:{RESET}")
    if not secret or not public:
        _info("1. Copy .env.example to .env and fill in your Paystack test keys")
        _info("   from dashboard.paystack.com → Settings → Developers")
    missing_codes = [p for p in db_plans if p.tier != "free" and not p.paystack_plan_code]
    if missing_codes:
        _info("2. Create these recurring plans in dashboard.paystack.com → Plans:")
        for plan in missing_codes:
            amount = plan.monthly_price_minor_units / 100
            _info(f"     • {plan.name}: {plan.currency} {amount:,.2f}/month")
        _info("3. Run: make paystack-sync  (or python -m app.paystack_sync_plans)")
        _info("   This auto-matches Paystack plans by name and saves the plan_code.")
    return problems


if __name__ == "__main__":
    sys.exit(main())
