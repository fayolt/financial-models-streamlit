"""Streamlit helper that renders per-format download buttons under a plugin page."""
from __future__ import annotations

from typing import Callable

from pydantic import BaseModel
import streamlit as st

from app.db import SessionLocal
from app.plugin.contract import Format, ModelPlugin, ModelResults, SubscriptionTier, User
from .commentary import (
    CommentaryError,
    QuotaExceeded as LLMQuotaExceeded,
    TIER_TOKEN_CAPS,
    generate_commentary,
    remaining_quota,
)
from .service import (
    FORMAT_TIER_REQUIRED,
    QuotaExceeded,
    TierTooLow,
    can_generate,
    generate_report_for_user,
    quota_remaining,
)


_MIME: dict[Format, str] = {
    Format.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    Format.PDF: "application/pdf",
    Format.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    Format.CSV: "text/csv",
}


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

    if not st.button(
        f"Generate {label}",
        use_container_width=True,
        type="primary",
        key=f"gen-{key_base}",
    ):
        return

    with st.spinner(f"Generating {label}…"):
        try:
            with SessionLocal() as db:
                data = generate_report_for_user(
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
            st.error(f"Report generation failed: {e}")
            return

    st.session_state[cached_key] = data
    st.rerun()


def render_commentary_section(
    plugin: ModelPlugin,
    inputs: BaseModel,
    results: ModelResults,
    user: User,
    summary_builder: Callable[[BaseModel, ModelResults], dict],
) -> None:
    """Enterprise-only: a button to generate LLM commentary on this model's run.

    `summary_builder` returns the dict that gets serialised into the LLM
    prompt — keep it focused (key metrics + key inputs only).
    """
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
    if cache_key in st.session_state:
        st.markdown(st.session_state[cache_key])
        if st.button("Regenerate", key=f"regen-comm-{plugin.slug}", disabled=remaining <= 0):
            st.session_state.pop(cache_key, None)
            st.rerun()
        return

    if st.button(
        "Generate AI commentary",
        type="primary",
        key=f"gen-comm-{plugin.slug}",
        disabled=remaining <= 0,
    ):
        with st.spinner("Calling the LLM…"):
            try:
                with SessionLocal() as _db:
                    text = generate_commentary(
                        db=_db,
                        user_id=user.id,
                        plugin_name=plugin.name,
                        description=plugin.description,
                        summary=summary_builder(inputs, results),
                    )
            except LLMQuotaExceeded as e:
                st.error(str(e))
                return
            except CommentaryError as e:
                st.error(f"Couldn't generate commentary: {e}")
                return
        st.session_state[cache_key] = text
        st.rerun()
