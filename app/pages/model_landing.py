"""Per-model landing page — template download + instructions + Create model CTA.

Each plugin page first shows this landing; clicking "Create model" sets a
session-state flag so subsequent renders show the plugin's actual workspace
(currently the minimal `plugin.render(...)` from the contract — a follow-up
will embed the submodule's full UI here)."""
from __future__ import annotations

import io

import streamlit as st

from app.plugin.contract import ModelPlugin


def _create_flag_key(slug: str) -> str:
    return f"_model_started_{slug}"


def is_started(slug: str) -> bool:
    """Whether the user has clicked Create on this model in the current session."""
    return bool(st.session_state.get(_create_flag_key(slug)))


def mark_started(slug: str) -> None:
    st.session_state[_create_flag_key(slug)] = True


def mark_not_started(slug: str) -> None:
    st.session_state.pop(_create_flag_key(slug), None)


def _template_bytes(plugin: ModelPlugin) -> bytes:
    """Build a minimal "input template" Excel from the plugin's input_schema.

    Returns a one-row workbook listing the schema field names with their
    default values. Placeholder for a richer per-model template later."""
    try:
        import pandas as pd

        defaults = plugin.default_inputs()
        # Pydantic v2 model dump → dict of field → default value
        row = defaults.model_dump() if hasattr(defaults, "model_dump") else dict(defaults)
        df = pd.DataFrame([row])
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Inputs")
        return buf.getvalue()
    except Exception:
        return b""


def render(plugin: ModelPlugin) -> None:
    """Render the landing card for one model."""
    with st.container(border=True):
        title = f"{plugin.icon} {plugin.name}" if plugin.icon else plugin.name
        st.title(title)
        st.caption(plugin.description)

        st.divider()

        st.markdown("**Downloadable template**")
        tpl = _template_bytes(plugin)
        col_dl, col_meta = st.columns([1, 3])
        with col_dl:
            st.download_button(
                "⬇️ Download template",
                data=tpl,
                file_name=f"{plugin.slug}-model-template.xlsx",
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
                key=f"landing-dl-{plugin.slug}",
                disabled=not tpl,
            )
        with col_meta:
            st.caption(f"Template: `{plugin.slug}-model-template.xlsx`")

        st.markdown("**Model creation instructions**")
        st.markdown(
            "1. Download the template and fill in the required assumptions.  \n"
            "2. Validate the inputs and make sure totals are consistent.  \n"
            "3. Create the model to launch the input workflow."
        )

        st.write("")
        if st.button(
            "➕ Create model",
            type="primary",
            key=f"landing-create-{plugin.slug}",
        ):
            mark_started(plugin.slug)
            st.rerun()


def render_coming_soon(plugin: ModelPlugin) -> None:
    """Placeholder shown for plugins flagged as 'coming soon'."""
    with st.container(border=True):
        title = f"{plugin.icon} {plugin.name}" if plugin.icon else plugin.name
        st.title(title)
        st.caption(plugin.description)
        st.divider()
        st.info("This model is **coming soon** — it isn't available for use yet.")
