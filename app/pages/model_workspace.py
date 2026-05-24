"""Per-model "workspace" renderers — what shows after the user clicks Create.

All 7 submodules use **Option C (inline import)**: we load each submodule's
`streamlit_app.py` into the same Streamlit process and call (or execute) its
rendering code directly.

How it works
------------
* **Models that expose `main()`** (biotech, cassava-ethanol, chicken-farming,
  goat-farming, microbrewery): import the module once (cached in sys.modules)
  then call `main()` on every rerun. Monkey-patch `st.set_page_config` before
  each call — whether set_page_config is inside `main()` or at module top-level
  the monkey-patch suppresses it either way.

* **pharma**: its `streamlit_app.py` is a thin launcher; the real entry point
  is `pharma_financial.app.main()`. We call that directly.

* **solar-farm**: no `main()` — the entire UI is rendered at module level.
  We re-execute the script on each rerun via `runpy.run_path()` with
  set_page_config patched out.

No session_state key collisions exist with our auth keys across all 7 models
(verified by grep — none of the submodules write to `session_state.user` or
`session_state.session_token`).
"""
from __future__ import annotations

import importlib.util
import runpy
import sys
from pathlib import Path
from typing import Any

import streamlit as st

_REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _patch_spc():
    """Return (original, patched) – caller must restore."""
    orig = st.set_page_config
    st.set_page_config = lambda *a, **kw: None
    return orig


def _load_module(module_name: str, app_path: Path, extra_sys_path: str | None = None) -> Any:
    """Import a submodule script once and cache it in sys.modules.

    Top-level code runs during the first load (function defs, imports, any
    module-level st.* calls).  set_page_config is suppressed so it doesn't
    conflict with our app's already-set config.  Subsequent calls return the
    cached module without re-executing.
    """
    if module_name in sys.modules:
        return sys.modules[module_name]

    submodule_dir = str(app_path.parent)
    for p in ([extra_sys_path] if extra_sys_path else []) + [submodule_dir]:
        if p and p not in sys.path:
            sys.path.insert(0, p)

    spec = importlib.util.spec_from_file_location(module_name, app_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not locate {app_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module

    orig = _patch_spc()
    try:
        spec.loader.exec_module(module)
    finally:
        st.set_page_config = orig

    return module


def _call_main(module: Any) -> None:
    """Call module.main() with set_page_config patched out."""
    orig = _patch_spc()
    try:
        module.main()
    finally:
        st.set_page_config = orig


def _render_error(slug: str, exc: Exception) -> None:
    # Only suggest re-initialising the submodule when the failure is
    # actually about a missing import or file path — otherwise the message
    # is misleading. e.g. a Streamlit st.secrets error or a runtime crash
    # has nothing to do with submodule init.
    is_init_problem = isinstance(exc, (ImportError, ModuleNotFoundError, FileNotFoundError))
    if is_init_problem:
        st.error(
            f"Could not load the **{slug}** submodule.  \n"
            f"`{exc}`  \n\n"
            "Make sure the submodule is initialised:  \n"
            f"`git submodule update --init {slug}`",
        )
    else:
        st.error(
            f"The **{slug}** model crashed while loading.  \n"
            f"`{type(exc).__name__}: {exc}`  \n\n"
            "This isn't a submodule-init issue — check the logs for the "
            "full traceback. The reference is in the structured logs.",
        )


# ---------------------------------------------------------------------------
# Individual renderers
# ---------------------------------------------------------------------------


def render_biotech_inline() -> None:
    try:
        module = _load_module(
            "_inline_biotech_app",
            _REPO_ROOT / "biotech" / "streamlit_app.py",
        )
        _call_main(module)
    except Exception as exc:
        _render_error("biotech", exc)


def render_cassava_ethanol_inline() -> None:
    try:
        module = _load_module(
            "_inline_cassava_ethanol_app",
            _REPO_ROOT / "cassava-ethanol" / "streamlit_app.py",
        )
        _call_main(module)
    except Exception as exc:
        _render_error("cassava-ethanol", exc)


def render_chicken_farming_inline() -> None:
    try:
        module = _load_module(
            "_inline_chicken_farming_app",
            _REPO_ROOT / "chicken-farming" / "streamlit_app.py",
        )
        _call_main(module)
    except Exception as exc:
        _render_error("chicken-farming", exc)


def render_goat_farming_inline() -> None:
    try:
        module = _load_module(
            "_inline_goat_farming_app",
            _REPO_ROOT / "goat-farming" / "streamlit_app.py",
        )
        _call_main(module)
    except Exception as exc:
        _render_error("goat-farming", exc)


def render_microbrewery_inline() -> None:
    try:
        module = _load_module(
            "_inline_microbrewery_app",
            _REPO_ROOT / "microbrewery" / "streamlit_app.py",
        )
        _call_main(module)
    except Exception as exc:
        _render_error("microbrewery", exc)


def render_pharma_inline() -> None:
    """pharma's streamlit_app.py is a thin launcher; call the real entry point."""
    try:
        pharma_src = str(_REPO_ROOT / "pharma" / "src")
        pharma_root = str(_REPO_ROOT / "pharma")
        for p in (pharma_src, pharma_root):
            if p not in sys.path:
                sys.path.insert(0, p)
        from pharma_financial.app import main as pharma_main  # noqa: PLC0415

        orig = _patch_spc()
        try:
            pharma_main()
        finally:
            st.set_page_config = orig
    except Exception as exc:
        _render_error("pharma", exc)


def render_solar_farm_inline() -> None:
    """solar-farm has no main() — re-execute the script on each rerun."""
    try:
        solar_dir = str(_REPO_ROOT / "solar-farm")
        if solar_dir not in sys.path:
            sys.path.insert(0, solar_dir)

        orig = _patch_spc()
        try:
            runpy.run_path(
                str(_REPO_ROOT / "solar-farm" / "streamlit_app.py"),
                run_name="__main__",
            )
        finally:
            st.set_page_config = orig
    except Exception as exc:
        _render_error("solar-farm", exc)
