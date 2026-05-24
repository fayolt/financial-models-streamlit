"""Models dashboard — grid of available model cards + Create New Model CTA."""
from __future__ import annotations

from typing import Callable

import streamlit as st

from app.plugin.contract import Format, ModelPlugin, SubscriptionTier

# Tier badge HTML: colour-coded pill shown on each model card.
_TIER_STYLE = {
    SubscriptionTier.FREE:       ("Free",       "#f1f5f9", "#64748b"),
    SubscriptionTier.PRO:        ("Pro",        "#dbeafe", "#1d4ed8"),
    SubscriptionTier.ENTERPRISE: ("Enterprise", "#fef3c7", "#b45309"),
}

# Format pill colours (bg, text).
_FMT_STYLE: dict[Format, tuple[str, str, str]] = {
    Format.XLSX: ("XLSX", "#dcfce7", "#166534"),
    Format.PDF:  ("PDF",  "#fee2e2", "#991b1b"),
    Format.DOCX: ("DOCX", "#ede9fe", "#5b21b6"),
    Format.CSV:  ("CSV",  "#e0f2fe", "#0369a1"),
}


def _tier_badge(tier: SubscriptionTier) -> str:
    label, bg, fg = _TIER_STYLE.get(tier, ("?", "#f1f5f9", "#64748b"))
    return (
        f"<span style='font-size:0.7rem;background:{bg};color:{fg};"
        f"padding:2px 8px;border-radius:10px;font-weight:600;'>{label}</span>"
    )


def _format_pills(formats: set[Format]) -> str:
    ordered = [f for f in (Format.XLSX, Format.CSV, Format.PDF, Format.DOCX) if f in formats]
    parts = []
    for fmt in ordered:
        label, bg, fg = _FMT_STYLE[fmt]
        parts.append(
            f"<span style='font-size:0.7rem;background:{bg};color:{fg};"
            f"padding:2px 6px;border-radius:8px;'>{label}</span>"
        )
    return "&nbsp;".join(parts)


def render(
    available_plugins: list[ModelPlugin],
    on_select: Callable[[str], None],
) -> None:
    st.title("Models")
    st.caption(
        "Create a new model and enter customer data before accessing dashboards."
    )
    st.write("")

    cards_per_row = 3
    items: list[ModelPlugin | None] = [None] + list(available_plugins)

    for row_start in range(0, len(items), cards_per_row):
        cols = st.columns(cards_per_row, gap="medium")
        for col, item in zip(cols, items[row_start : row_start + cards_per_row]):
            with col:
                if item is None:
                    _render_create_new_card(available_plugins, on_select)
                else:
                    _render_plugin_card(item, on_select)


def _render_create_new_card(
    available_plugins: list[ModelPlugin],
    on_select: Callable[[str], None],
) -> None:
    _PICKER_KEY = "dashboard_create_new_open"
    with st.container(border=True):
        st.subheader("Create New Model")
        st.caption("Choose a model to start a new customer form.")
        st.write("")

        if not st.session_state.get(_PICKER_KEY):
            st.caption(
                "Select a model and complete the input form before other "
                "dashboards unlock."
            )
            st.write("")
            if st.button(
                "➕ Choose Model",
                type="primary",
                use_container_width=True,
                key="dashboard-create-new-cta",
            ):
                st.session_state[_PICKER_KEY] = True
                st.rerun()
        else:
            st.caption("Select a model to get started:")
            for plugin in available_plugins:
                label = f"{plugin.icon}  {plugin.name}" if plugin.icon else plugin.name
                if st.button(
                    label,
                    key=f"create-new-pick-{plugin.slug}",
                    use_container_width=True,
                ):
                    st.session_state[_PICKER_KEY] = False
                    on_select(plugin.slug)
            st.write("")
            if st.button(
                "✕ Cancel",
                key="dashboard-create-new-cancel",
                use_container_width=True,
            ):
                st.session_state[_PICKER_KEY] = False
                st.rerun()


def _render_plugin_card(plugin: ModelPlugin, on_select: Callable[[str], None]) -> None:
    with st.container(border=True):
        # Title row: icon + name + tier badge
        title = f"{plugin.icon} {plugin.name}" if plugin.icon else plugin.name
        badge = _tier_badge(plugin.minimum_tier)
        st.markdown(
            f"<div style='display:flex;align-items:center;justify-content:space-between;"
            f"gap:0.5rem;margin-bottom:0.25rem;'>"
            f"<span style='font-size:1.1rem;font-weight:600;'>{title}</span>"
            f"{badge}</div>",
            unsafe_allow_html=True,
        )
        st.caption(plugin.description)

        # Format tags
        if plugin.supported_formats:
            pills = _format_pills(plugin.supported_formats)
            st.markdown(
                f"<div style='margin:0.5rem 0 0.75rem;'>{pills}</div>",
                unsafe_allow_html=True,
            )
        else:
            st.write("")

        if st.button(
            "Select",
            type="primary",
            use_container_width=True,
            key=f"dashboard-select-{plugin.slug}",
        ):
            on_select(plugin.slug)
