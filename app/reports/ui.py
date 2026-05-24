"""Streamlit helper that renders per-format download buttons under a plugin page."""
from __future__ import annotations

from typing import Callable
from uuid import UUID

from pydantic import BaseModel
import streamlit as st

from app.db import SessionLocal
from app.plugin.contract import Format, ModelPlugin, ModelResults, SubscriptionTier, User
from .background import (
    BackgroundCommentaryStatus,
    BackgroundRunStatus,
    poll_commentary_run,
    poll_report_run,
    reap_stale_jobs,
    submit_commentary_job,
    submit_report_job,
)
from .commentary import (
    CommentaryError,
    QuotaExceeded as LLMQuotaExceeded,
    TIER_TOKEN_CAPS,
    remaining_quota,
)
from .service import (
    FORMAT_TIER_REQUIRED,
    QuotaExceeded,
    TierTooLow,
    can_generate,
    quota_remaining,
)


_MIME: dict[Format, str] = {
    Format.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    Format.PDF: "application/pdf",
    Format.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    Format.CSV: "text/csv",
}


# ---------------------------------------------------------------------------
# Module-level fragment functions (must be at module scope for Streamlit)
# ---------------------------------------------------------------------------


@st.fragment(run_every=2)
def _poll_report_fragment(pending_key: str, cached_key: str, run_id_str: str) -> None:
    """Reruns every 2 s. On completion transitions to the download-button state."""
    with SessionLocal() as db:
        result: BackgroundRunStatus = poll_report_run(db, UUID(run_id_str))

    if result.status == "pending":
        st.info("Generating report… this may take up to 30 seconds.")
        return  # fragment auto-reruns in 2 s

    if result.status == "failed":
        st.session_state.pop(pending_key, None)
        st.error(
            f"Report generation failed: {result.error_message or 'Unknown error'}. "
            "Please try again."
        )
        st.rerun()
        return

    # success — load bytes into session state, trigger full rerun so
    # _render_one_format picks up the cached_key branch and shows download button.
    st.session_state.pop(pending_key, None)
    st.session_state[cached_key] = result.file_data
    st.rerun()


@st.fragment(run_every=2)
def _poll_commentary_fragment(pending_key: str, cache_key: str, run_id_str: str) -> None:
    """Reruns every 2 s. On completion transitions to the text-display state."""
    with SessionLocal() as db:
        result: BackgroundCommentaryStatus = poll_commentary_run(db, UUID(run_id_str))

    if result.status == "pending":
        st.info("Generating AI commentary… this usually takes 5–15 seconds.")
        return

    if result.status == "failed":
        st.session_state.pop(pending_key, None)
        st.error(
            f"Commentary generation failed: {result.error_message or 'Unknown error'}"
        )
        st.rerun()
        return

    st.session_state.pop(pending_key, None)
    st.session_state[cache_key] = result.commentary_text
    st.rerun()


# ---------------------------------------------------------------------------
# Public render functions
# ---------------------------------------------------------------------------


def render_report_downloads(
    plugin: ModelPlugin,
    inputs: BaseModel,
    results: ModelResults,
    user: User,
) -> None:
    if not plugin.supported_formats:
        return

    user_tier = user.tier.value
    user_id = user.id

    st.divider()
    st.subheader("Download report")

    with SessionLocal() as db:
        remaining = quota_remaining(db, user_id)
        reap_stale_jobs(db)  # clean up stuck pending rows from prior restarts

    if remaining is None:
        st.caption("Unlimited reports this month.")
    elif remaining == 0 and user_tier == "free":
        st.caption("Reports are available on Pro and Enterprise plans.")
    else:
        st.caption(f"{remaining} report(s) remaining this month.")

    formats_sorted = sorted(plugin.supported_formats, key=lambda f: f.value)
    cols = st.columns(len(formats_sorted))

    for col, fmt in zip(cols, formats_sorted):
        with col:
            _render_one_format(plugin, inputs, results, user, fmt, remaining)


def _render_one_format(
    plugin: ModelPlugin,
    inputs: BaseModel,
    results: ModelResults,
    user: User,
    fmt: Format,
    remaining: int | None,
) -> None:
    label = fmt.value.upper()
    key_base = f"{plugin.slug}-{fmt.value}"
    user_tier = user.tier.value

    # ── Tier gate (unchanged) ────────────────────────────────────────────────
    if not can_generate(user_tier=user_tier, fmt=fmt):
        required = FORMAT_TIER_REQUIRED[fmt]
        st.button(
            f"{label} ({required.value.title()})",
            disabled=True,
            help=f"Upgrade to {required.value.title()} to unlock {label} exports.",
            use_container_width=True,
            key=f"locked-{key_base}",
        )
        return

    if remaining is not None and remaining <= 0:
        st.button(
            f"{label} (quota exhausted)",
            disabled=True,
            help="Your monthly report quota is used up. Upgrade to Enterprise for unlimited.",
            use_container_width=True,
            key=f"quota-{key_base}",
        )
        return

    cached_key = f"report_bytes::{key_base}"
    pending_key = f"report_pending::{key_base}"

    # ── State 1: bytes ready → show download button (unchanged path) ─────────
    if cached_key in st.session_state:
        data = st.session_state[cached_key]
        st.download_button(
            f"Download {label}",
            data=data,
            file_name=f"{plugin.slug}_report.{fmt.value}",
            mime=_MIME.get(fmt, "application/octet-stream"),
            use_container_width=True,
            key=f"dl-{key_base}",
        )
        return

    # ── State 2: background job running → show polling fragment ──────────────
    if pending_key in st.session_state:
        run_id_str = str(st.session_state[pending_key])
        _poll_report_fragment(pending_key, cached_key, run_id_str)
        return

    # ── State 3: idle → show Generate button ─────────────────────────────────
    if not st.button(
        f"Generate {label}",
        use_container_width=True,
        type="primary",
        key=f"gen-{key_base}",
    ):
        return

    try:
        with SessionLocal() as db:
            run_id = submit_report_job(
                db,
                plugin=plugin,
                inputs=inputs,
                results=results,
                fmt=fmt,
                user_id=user.id,
            )
    except TierTooLow as e:
        st.error(str(e))
        return
    except QuotaExceeded as e:
        st.error(str(e))
        return
    except Exception as e:
        st.error(f"Could not start report generation: {e}")
        return

    st.session_state[pending_key] = run_id
    st.rerun()


def render_commentary_section(
    plugin: ModelPlugin,
    inputs: BaseModel,
    results: ModelResults,
    user: User,
    summary_builder: Callable[[BaseModel, ModelResults], dict],
) -> None:
    """Enterprise-only: generate LLM commentary on this model's run (non-blocking)."""
    st.divider()
    st.subheader("AI commentary")

    if user.tier != SubscriptionTier.ENTERPRISE:
        st.info("AI-generated executive commentary is an Enterprise-tier feature.")
        return

    with SessionLocal() as _db:
        remaining = remaining_quota(_db, user.id)
    cap = TIER_TOKEN_CAPS.get(user.tier.value, 0)
    used = max(0, cap - remaining)
    st.caption(f"Monthly AI budget: {used:,} / {cap:,} tokens used  ·  {remaining:,} remaining")

    cache_key = f"commentary::{plugin.slug}"
    pending_key = f"commentary_pending::{plugin.slug}"

    # ── State 1: commentary cached → show text + regenerate ──────────────────
    if cache_key in st.session_state:
        st.markdown(st.session_state[cache_key])
        if st.button("Regenerate", key=f"regen-comm-{plugin.slug}", disabled=remaining <= 0):
            st.session_state.pop(cache_key, None)
            st.rerun()
        return

    # ── State 2: background job running → show polling fragment ──────────────
    if pending_key in st.session_state:
        run_id_str = str(st.session_state[pending_key])
        _poll_commentary_fragment(pending_key, cache_key, run_id_str)
        return

    # ── State 3: idle → show Generate button ─────────────────────────────────
    if not st.button(
        "Generate AI commentary",
        type="primary",
        key=f"gen-comm-{plugin.slug}",
        disabled=remaining <= 0,
    ):
        return

    try:
        summary = summary_builder(inputs, results)
        with SessionLocal() as db:
            run_id = submit_commentary_job(
                db,
                user_id=user.id,
                model_slug=plugin.slug,
                plugin_name=plugin.name,
                description=plugin.description,
                summary=summary,
            )
    except LLMQuotaExceeded as e:
        st.error(str(e))
        return
    except CommentaryError as e:
        st.error(f"Couldn't start commentary generation: {e}")
        return
    except Exception as e:
        st.error(f"Could not start commentary generation: {e}")
        return

    st.session_state[pending_key] = run_id
    st.rerun()
