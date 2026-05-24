"""Background report and commentary generation using Python daemon threads.

Design
------
* `submit_report_job` / `submit_commentary_job` each:
    1. Run synchronous tier/quota checks (cheap DB reads).
    2. Insert a 'pending' row into report_runs / commentary_runs.
    3. Start a daemon thread that calls the blocking generation code.
    4. Return the run UUID immediately — the caller stores it in session_state
       and polls with `poll_report_run` / `poll_commentary_run`.

* Each thread opens its own `SessionLocal()` so it never touches the
  caller's session. `inputs` and `results` are Pydantic models (immutable
  value objects); plugins are `@st.cache_resource` singletons (read-only).

* Stale cleanup: daemon threads die when Streamlit restarts on deploy.
  `reap_stale_jobs(db)` marks any 'pending' row older than STALE_THRESHOLD
  as 'failed'. Called once per page load from `render_report_downloads`.

Upgrade path to a worker process (Option B)
--------------------------------------------
Remove the `threading.Thread` calls from `submit_*_job`; add a new
`api/worker.py` that polls `FOR UPDATE SKIP LOCKED` and calls the same
`_generate_report_in_thread` / `_generate_commentary_in_thread` logic.
The UI polling fragment works unchanged — it only reads DB status.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session as SASession

from app.db import SessionLocal
from app.db.models import CommentaryRun, ReportRun, User
from app.plugin.contract import (
    Format,
    ModelPlugin,
    ModelResults,
    ReportOptions,
    SubscriptionTier,
    User as PluginUser,
)
from app.reports.service import (
    FORMAT_TIER_REQUIRED,
    QuotaExceeded,
    TierTooLow,
    can_generate,
    quota_remaining,
)

_log = logging.getLogger("app.reports.background")

STALE_THRESHOLD = timedelta(minutes=10)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class BackgroundRunStatus:
    status: str           # 'pending' | 'success' | 'failed'
    file_data: bytes | None
    error_message: str | None
    run_id: UUID


@dataclass
class BackgroundCommentaryStatus:
    status: str           # 'pending' | 'success' | 'failed'
    commentary_text: str | None
    error_message: str | None
    run_id: UUID


# ---------------------------------------------------------------------------
# Report job
# ---------------------------------------------------------------------------


def submit_report_job(
    db: SASession,
    *,
    plugin: ModelPlugin,
    inputs,
    results: ModelResults,
    fmt: Format,
    user_id: UUID,
    options: ReportOptions | None = None,
) -> UUID:
    """Tier-gate + quota-check, create a pending row, launch daemon thread.

    Returns the run UUID immediately. Raises TierTooLow / QuotaExceeded
    before creating any row so the caller can surface the error inline.
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

    # Serialise inputs for the future worker upgrade path.
    try:
        inputs_json = inputs.model_dump(mode="json")
    except Exception:
        inputs_json = None

    run = ReportRun(
        user_id=user_id,
        model_slug=plugin.slug,
        format=fmt.value,
        status="pending",
        inputs_json=inputs_json,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    run_id = run.id

    plugin_user = PluginUser(
        id=user.id,
        email=user.email,
        tier=SubscriptionTier(user.tier),
    )

    t = threading.Thread(
        target=_generate_report_in_thread,
        args=(run_id, plugin, inputs, results, fmt, options or ReportOptions(), plugin_user),
        daemon=True,
        name=f"report-{str(run_id)[:8]}",
    )
    t.start()
    _log.info(
        "report job submitted run_id=%s slug=%s fmt=%s",
        run_id, plugin.slug, fmt.value,
    )
    return run_id


def _generate_report_in_thread(
    run_id: UUID,
    plugin: ModelPlugin,
    inputs,
    results: ModelResults,
    fmt: Format,
    options: ReportOptions,
    plugin_user: PluginUser,
) -> None:
    try:
        output = plugin.generate_report(
            inputs=inputs,
            results=results,
            formats={fmt},
            options=options,
            user=plugin_user,
        )
        data = output.get(fmt) or b""
        if not data:
            raise RuntimeError("Plugin returned empty bytes.")
    except Exception as exc:
        _log.exception("report generation failed run_id=%s", run_id)
        _write_report_outcome(run_id, status="failed", error_message=str(exc)[:1000])
        return

    _write_report_outcome(run_id, status="success", file_data=data)
    _log.info("report done run_id=%s bytes=%d", run_id, len(data))


def _write_report_outcome(
    run_id: UUID,
    *,
    status: str,
    file_data: bytes | None = None,
    error_message: str | None = None,
) -> None:
    try:
        with SessionLocal() as db:
            run = db.get(ReportRun, run_id)
            if run is None:
                return
            run.status = status
            run.completed_at = datetime.now(timezone.utc)
            if file_data is not None:
                run.file_data = file_data
                run.bytes_size = len(file_data)
            if error_message is not None:
                run.error_message = error_message
            db.commit()
    except Exception:
        _log.exception("_write_report_outcome failed run_id=%s", run_id)


def poll_report_run(db: SASession, run_id: UUID) -> BackgroundRunStatus:
    """Fetch the current state of a report run. Safe to call on every poll tick."""
    run = db.get(ReportRun, run_id)
    if run is None:
        return BackgroundRunStatus(
            status="failed",
            file_data=None,
            error_message="Run not found — it may have been cleaned up.",
            run_id=run_id,
        )
    return BackgroundRunStatus(
        status=run.status,
        file_data=run.file_data,
        error_message=run.error_message,
        run_id=run.id,
    )


# ---------------------------------------------------------------------------
# Commentary job
# ---------------------------------------------------------------------------


def submit_commentary_job(
    db: SASession,
    *,
    user_id: UUID,
    model_slug: str,
    plugin_name: str,
    description: str,
    summary: dict[str, Any],
) -> UUID:
    """Create a pending commentary row and start a daemon thread.

    Token quota is re-checked inside the thread just before the LLM call
    (inside `generate_commentary`) so we don't double-bill on retries.
    """
    run = CommentaryRun(
        user_id=user_id,
        model_slug=model_slug,
        status="pending",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    run_id = run.id

    t = threading.Thread(
        target=_generate_commentary_in_thread,
        args=(run_id, user_id, plugin_name, description, summary),
        daemon=True,
        name=f"comm-{str(run_id)[:8]}",
    )
    t.start()
    _log.info("commentary job submitted run_id=%s slug=%s", run_id, model_slug)
    return run_id


def _generate_commentary_in_thread(
    run_id: UUID,
    user_id: UUID,
    plugin_name: str,
    description: str,
    summary: dict[str, Any],
) -> None:
    from app.reports.commentary import CommentaryError, generate_commentary

    try:
        with SessionLocal() as db:
            text = generate_commentary(
                db=db,
                user_id=user_id,
                plugin_name=plugin_name,
                description=description,
                summary=summary,
            )
    except CommentaryError as exc:
        _write_commentary_outcome(run_id, status="failed", error_message=str(exc))
        return
    except Exception as exc:
        _log.exception("commentary generation failed run_id=%s", run_id)
        _write_commentary_outcome(run_id, status="failed", error_message=str(exc)[:1000])
        return

    _write_commentary_outcome(run_id, status="success", commentary_text=text)
    _log.info("commentary done run_id=%s", run_id)


def _write_commentary_outcome(
    run_id: UUID,
    *,
    status: str,
    commentary_text: str | None = None,
    error_message: str | None = None,
) -> None:
    try:
        with SessionLocal() as db:
            run = db.get(CommentaryRun, run_id)
            if run is None:
                return
            run.status = status
            run.completed_at = datetime.now(timezone.utc)
            if commentary_text is not None:
                run.commentary_text = commentary_text
            if error_message is not None:
                run.error_message = error_message
            db.commit()
    except Exception:
        _log.exception("_write_commentary_outcome failed run_id=%s", run_id)


def poll_commentary_run(db: SASession, run_id: UUID) -> BackgroundCommentaryStatus:
    run = db.get(CommentaryRun, run_id)
    if run is None:
        return BackgroundCommentaryStatus(
            status="failed",
            commentary_text=None,
            error_message="Run not found — it may have been cleaned up.",
            run_id=run_id,
        )
    return BackgroundCommentaryStatus(
        status=run.status,
        commentary_text=run.commentary_text,
        error_message=run.error_message,
        run_id=run.id,
    )


# ---------------------------------------------------------------------------
# Stale job cleanup
# ---------------------------------------------------------------------------


def reap_stale_jobs(db: SASession) -> int:
    """Mark pending rows older than STALE_THRESHOLD as failed.

    Called once per page load (before the polling fragment renders) so users
    don't see a stuck spinner after a Streamlit restart killed the thread.
    Returns the number of rows updated.
    """
    cutoff = datetime.now(timezone.utc) - STALE_THRESHOLD
    count = 0

    for model_cls in (ReportRun, CommentaryRun):
        stale = (
            db.query(model_cls)
            .filter(model_cls.status == "pending")
            .filter(model_cls.started_at < cutoff)
            .all()
        )
        for row in stale:
            row.status = "failed"
            row.error_message = "Generation timed out (restart or crash) — please try again."
            row.completed_at = datetime.now(timezone.utc)
        count += len(stale)

    if count:
        db.commit()
        _log.warning("reaped %d stale background jobs", count)
    return count
