"""Models dashboard — grid of available model cards + Create New Model CTA."""
from __future__ import annotations

from typing import Callable

import streamlit as st

from app.plugin.contract import ModelPlugin


def render(
    available_plugins: list[ModelPlugin],
    on_select: Callable[[str], None],
) -> None:
    """Render the Models grid.

    `on_select(slug)` is called when the user clicks a plugin's Select
    button — the caller wires it to st.switch_page or a state mutation."""
    st.title("Models")
    st.caption(
        "Create a new model and enter customer data before accessing dashboards."
    )
    st.write("")

    cards_per_row = 3
    # The "Create New Model" card occupies the first slot, then each available
    # plugin gets its own card.
    items: list[ModelPlugin | None] = [None] + list(available_plugins)

    for row_start in range(0, len(items), cards_per_row):
        cols = st.columns(cards_per_row, gap="medium")
        for col, item in zip(cols, items[row_start : row_start + cards_per_row]):
            with col:
                if item is None:
                    _render_create_new_card()
                else:
                    _render_plugin_card(item, on_select)


def _render_create_new_card() -> None:
    with st.container(border=True):
        st.subheader("Create New Model")
        st.caption("Choose a model to start a new customer form.")
        st.write("")
        st.caption(
            "Select a model and complete the input form before other "
            "dashboards unlock."
        )
        st.write("")
        st.button(
            "➕ Choose Model",
            type="primary",
            use_container_width=True,
            disabled=True,
            key="dashboard-create-new-cta",
            help="Pick a model card on the right to start.",
        )


def _render_plugin_card(plugin: ModelPlugin, on_select: Callable[[str], None]) -> None:
    with st.container(border=True):
        title = f"{plugin.icon} {plugin.name}" if plugin.icon else plugin.name
        st.subheader(title)
        st.caption(plugin.description)
        st.write("")
        if st.button(
            "Select",
            type="primary",
            use_container_width=True,
            key=f"dashboard-select-{plugin.slug}",
        ):
            on_select(plugin.slug)
