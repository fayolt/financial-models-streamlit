"""Report generation service: tier gating, monthly quota, and report_runs audit."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import Session as SASession

from app.auth.gating import user_meets_tier
from app.db.models import Plan, ReportRun, User
from app.plugin.contract import (
    Format,
    ModelPlugin,
    ModelResults,
    NotSupportedError,
    ReportOptions,
    SubscriptionTier,
    User as PluginUser,
)


# Which subscription tier unlocks each output format.
# Free can view models on screen but exports require Pro; PDF/DOCX require Enterprise.
FORMAT_TIER_REQUIRED: dict[Format, SubscriptionTier] = {
    Format.XLSX: SubscriptionTier.PRO,
    Format.CSV: SubscriptionTier.PRO,
    Format.PDF: SubscriptionTier.ENTERPRISE,
    Format.DOCX: SubscriptionTier.ENTERPRISE,
}


class TierTooLow(Exception):
    """User's subscription tier is below what the requested format needs."""


class QuotaExceeded(Exception):
    """User has exhausted this month's report quota."""


def can_generate(*, user_tier: str, fmt: Format) -> bool:
    required = FORMAT_TIER_REQUIRED.get(fmt, SubscriptionTier.ENTERPRISE)
    return user_meets_tier(user_tier, required)


def quota_remaining(db: SASession, user_id: UUID) -> int | None:
    """Return remaining reports this calendar month, or None for unlimited.

    Resolves the quota from the user's *tier-matching Plan*, not from their
    Subscription row, so tier changes apply immediately.
    """
    user = db.get(User, user_id)
    if user is None or user.tier == "free":
        return 0
    if user.tier == "enterprise":
        return None
    plan = db.query(Plan).filter_by(tier=user.tier, is_active=True).first()
    if plan is None:
        return 0
    if plan.monthly_report_quota is None:
        return None
    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    used = (
        db.query(ReportRun)
        .filter_by(user_id=user_id, status="success")
        .filter(ReportRun.started_at >= month_start)
        .count()
    )
    return max(0, plan.monthly_report_quota - used)


def generate_report_for_user(
    db: SASession,
    *,
    plugin: ModelPlugin,
    inputs: BaseModel,
    results: ModelResults,
    fmt: Format,
    user_id: UUID,
    options: ReportOptions | None = None,
) -> bytes:
    """Tier-gate, quota-check, generate, audit. Returns the report bytes.

    Raises TierTooLow / QuotaExceeded / NotSupportedError / RuntimeError.
    Every attempt — success or failure — is recorded in report_runs.
    """
    user = db.get(User, user_id)
    if user is None:
        raise TierTooLow("Unknown user.")

    if not can_generate(user_tier=user.tier, fmt=fmt):
        required = FORMAT_TIER_REQUIRED[fmt]
        raise TierTooLow(
            f"{fmt.value.upper()} export requires the {required.value.title()} tier."
        )

    remaining = quota_remaining(db, user_id)
    if remaining is not None and remaining <= 0:
        raise QuotaExceeded("Monthly report quota exhausted.")

    run = ReportRun(
        user_id=user_id,
        model_slug=plugin.slug,
        format=fmt.value,
        status="pending",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    plugin_user = PluginUser(
        id=user.id, email=user.email, tier=SubscriptionTier(user.tier)
    )

    try:
        output = plugin.generate_report(
            inputs=inputs,
            results=results,
            formats={fmt},
            options=options or ReportOptions(),
            user=plugin_user,
        )
    except NotSupportedError as e:
        run.status = "failed"
        run.error_message = f"Not supported: {e}"
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        raise
    except Exception as e:
        run.status = "failed"
        run.error_message = str(e)[:1000]
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        raise

    data = output.get(fmt) or b""
    if not data:
        run.status = "failed"
        run.error_message = "Plugin returned empty bytes."
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        raise RuntimeError("Plugin returned empty bytes.")

    run.status = "success"
    run.bytes_size = len(data)
    run.completed_at = datetime.now(timezone.utc)
    db.commit()

    return data
