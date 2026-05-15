"""Per-model "workspace" renderers — what shows after the user clicks Create.

Two integration patterns are demonstrated here, one per model:

1. **Inline import** (`render_biotech_inline`): we load the submodule's
   `streamlit_app.py` as a Python module, monkey-patch `st.set_page_config`
   (already called once by the unified app), and call its `main()`. The
   submodule renders into the same Streamlit page as the unified app — no
   extra process, no iframe, full access to our auth + session state. The
   submodule MUST already expose a `main()` and its top-level code must
   not have widget side-effects beyond what `main()` handles.

2. **Iframe** (`render_pharma_iframe`): we run the submodule as a
   completely separate Streamlit process on a private port, and embed it
   in our page via `st.components.v1.iframe`. Total isolation; zero
   submodule changes; visible chrome seam.

Pick whichever fits the submodule's existing shape. After both are in
place we can pick a winner per submodule.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import streamlit as st


_REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Pattern 1 — inline import (used by biotech)
# ---------------------------------------------------------------------------


_BIOTECH_MODULE_NAME = "_inline_biotech_app"


def _load_biotech_module():
    """Import biotech/streamlit_app.py once and cache it in sys.modules.

    Top-level code in that file is just imports + function defs — no widget
    calls — so loading it does not produce Streamlit output. The actual UI
    runs only when we call its `main()`.
    """
    if _BIOTECH_MODULE_NAME in sys.modules:
        return sys.modules[_BIOTECH_MODULE_NAME]

    biotech_dir = str(_REPO_ROOT / "biotech")
    if biotech_dir not in sys.path:
        sys.path.insert(0, biotech_dir)

    spec = importlib.util.spec_from_file_location(
        _BIOTECH_MODULE_NAME, _REPO_ROOT / "biotech" / "streamlit_app.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not locate biotech/streamlit_app.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_BIOTECH_MODULE_NAME] = module

    # biotech's main() calls st.set_page_config; the unified app has already
    # called it. Patch it out for the duration of the module load + main
    # invocation. Doing it here protects against any future top-level
    # set_page_config call too.
    original = st.set_page_config
    st.set_page_config = lambda *a, **kw: None
    try:
        spec.loader.exec_module(module)
    finally:
        st.set_page_config = original

    return module


def render_biotech_inline() -> None:
    try:
        module = _load_biotech_module()
    except Exception as e:
        st.error(
            f"Could not load biotech submodule: {e}. "
            "Check that `biotech/` is initialised "
            "(`git submodule update --init biotech`)."
        )
        return

    original = st.set_page_config
    st.set_page_config = lambda *a, **kw: None
    try:
        module.main()
    finally:
        st.set_page_config = original


# ---------------------------------------------------------------------------
# Pattern 2 — iframe (used by pharma)
# ---------------------------------------------------------------------------


def _pharma_iframe_url() -> str:
    base = os.environ.get(
        "PHARMA_APP_URL", "http://localhost:8511"
    ).rstrip("/")
    # `?embed=true` strips Streamlit's top toolbar/footer for a cleaner embed.
    return (
        f"{base}/?embed=true&embed_options=show_padding"
    )


def render_pharma_iframe() -> None:
    st.info(
        "The pharma workspace runs as a **separate Streamlit process** on "
        "port 8511. Start it in another terminal with `make pharma-app`, then "
        "this iframe will render its UI below.",
        icon="ℹ️",
    )
    st.components.v1.iframe(
        _pharma_iframe_url(),
        height=1400,
        scrolling=True,
    )
