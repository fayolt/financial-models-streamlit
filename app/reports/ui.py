"""Streamlit helper that renders per-format download buttons under a plugin page."""
from __future__ import annotations

from pydantic import BaseModel
import streamlit as st

from app.db import SessionLocal
from app.plugin.contract import Format, ModelPlugin, ModelResults, User
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
