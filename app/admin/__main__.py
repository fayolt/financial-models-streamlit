"""CLI for bootstrapping admins.

Usage:
    python -m app.admin promote you@example.com
    python -m app.admin demote you@example.com
    python -m app.admin list
"""
from __future__ import annotations

import argparse
import sys

from app.db import SessionLocal
from app.db.models import User


def promote(email: str) -> int:
    email = email.strip().lower()
    with SessionLocal() as db:
        user = db.query(User).filter_by(email=email).first()
        if not user:
            print(f"No user with email {email}", file=sys.stderr)
            return 1
        if user.is_admin:
            print(f"{email} is already an admin")
            return 0
        user.is_admin = True
        db.commit()
        print(f"Promoted {email} to admin")
        return 0


def demote(email: str) -> int:
    email = email.strip().lower()
    with SessionLocal() as db:
        user = db.query(User).filter_by(email=email).first()
        if not user:
            print(f"No user with email {email}", file=sys.stderr)
            return 1
        if not user.is_admin:
            print(f"{email} is not an admin")
            return 0
        user.is_admin = False
        db.commit()
        print(f"Demoted {email}")
        return 0


def list_admins() -> int:
    with SessionLocal() as db:
        admins = db.query(User).filter_by(is_admin=True).order_by(User.email).all()
    if not admins:
        print("No admins yet. Promote one with: python -m app.admin promote <email>")
        return 0
    for u in admins:
        print(f"{u.email}\t(id={u.id})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.admin")
    sub = parser.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("promote", help="Grant admin to a user")
    pr.add_argument("email")
    dm = sub.add_parser("demote", help="Revoke admin from a user")
    dm.add_argument("email")
    sub.add_parser("list", help="List current admins")
    args = parser.parse_args()
    if args.cmd == "promote":
        return promote(args.email)
    if args.cmd == "demote":
        return demote(args.email)
    if args.cmd == "list":
        return list_admins()
    return 1


if __name__ == "__main__":
    sys.exit(main())
