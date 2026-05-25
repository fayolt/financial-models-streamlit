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
import threading
from pathlib import Path
from typing import Any

import streamlit as st

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Per-module threading.Event — set when a module is fully initialised.
# Prevents the main thread from using a partially-initialised module that a
# background pre-warm thread is still running exec_module on.
_MODULE_READY: dict[str, threading.Event] = {}
_MODULE_LOCK = threading.Lock()


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

    Thread-safe: if a background pre-warm thread is mid-way through
    exec_module, the main thread waits for it to complete before returning
    the module — preventing use of a partially-initialised module.
    """
    # Fast path: already loaded. Wait if still initialising (pre-warm in progress).
    if module_name in sys.modules:
        with _MODULE_LOCK:
            event = _MODULE_READY.get(module_name)
        if event is not None:
            event.wait(timeout=60)
        return sys.modules[module_name]

    # Claim the module slot under lock so parallel callers don't double-load.
    with _MODULE_LOCK:
        if module_name in sys.modules:
            event = _MODULE_READY.get(module_name)
            if event is not None:
                event.wait(timeout=60)
            return sys.modules[module_name]
        ready = threading.Event()
        _MODULE_READY[module_name] = ready

    submodule_dir = str(app_path.parent)
    for p in ([extra_sys_path] if extra_sys_path else []) + [submodule_dir]:
        if p and p not in sys.path:
            sys.path.insert(0, p)

    spec = importlib.util.spec_from_file_location(module_name, app_path)
    if spec is None or spec.loader is None:
        ready.set()
        raise RuntimeError(f"Could not locate {app_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module

    orig = _patch_spc()
    try:
        spec.loader.exec_module(module)
    except Exception:
        ready.set()
        raise
    finally:
        st.set_page_config = orig

    ready.set()
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


def _patch_cassava_annual_sync(module: Any) -> None:
    """Monkey-patch _sync_projection_from_session to also shift annual table years.

    The upstream submodule shifts monthly table columns when the projection
    horizon changes, but leaves the integer Year columns in inflation_schedule
    and production_annual untouched. That causes a validation error:
      ValueError: Inflation Schedule: year values must be within projection horizon

    We can't push fixes to the upstream Kossit73/Cassava_Ethanol repo, so we
    patch the already-loaded module in-process. The patch is idempotent —
    re-loading from sys.modules returns the already-patched function.
    """
    if getattr(module, "_annual_sync_patched", False):
        return

    orig = getattr(module, "_sync_projection_from_session", None)
    if orig is None:
        return

    import pandas as _pd

    def _shift_year_col(tbl: Any, delta: int) -> None:
        """Shift integer Year column values by delta in an EditableTable."""
        try:
            df = tbl.data
            col = next((c for c in df.columns if str(c).lower() == "year"), None)
            if col is None or delta == 0:
                return
            years = _pd.to_numeric(df[col], errors="coerce")
            if years.isna().any():
                return
            df.loc[:, col] = (years + delta).astype(int)
        except Exception:
            pass  # never block rendering over a shift failure

    def _patched(page: Any) -> None:
        prev_start = int(page.projection.start_year)
        orig(page)
        delta = int(page.projection.start_year) - prev_start
        if delta:
            _shift_year_col(page.inflation_schedule, delta)
            _shift_year_col(page.production_annual, delta)

    module._sync_projection_from_session = _patched
    module._annual_sync_patched = True


def render_cassava_ethanol_inline() -> None:
    try:
        module = _load_module(
            "_inline_cassava_ethanol_app",
            _REPO_ROOT / "cassava-ethanol" / "streamlit_app.py",
        )
        _patch_cassava_annual_sync(module)
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


_SIDEBAR_HIDING_TARGETS = ("stSidebar", "stSidebarNav", "collapsedControl")


def _patch_markdown_strip_sidebar_css():
    """Return (original, patched) for st.markdown.

    solar-farm injects `display:none` CSS targeting stSidebar / collapsedControl
    so its standalone app fills the full viewport. Patching st.markdown lets us
    strip those rules before they reach the browser — same pattern as _patch_spc.
    """
    import re as _re

    orig = st.markdown

    def _stripped(body, *args, **kwargs):
        if isinstance(body, str) and any(t in body for t in _SIDEBAR_HIDING_TARGETS):
            # Remove the CSS rule block that hides our navigation sidebar.
            # Pattern matches from the first sidebar selector up to (and
            # including) the closing brace of the multi-selector rule block.
            body = _re.sub(
                r"\[data-testid=[\"'](?:stSidebar|stSidebarNav|collapsedControl)[\"'][^\]]*\][^}]*\}",
                "",
                body,
                flags=_re.DOTALL | _re.IGNORECASE,
            )
        return orig(body, *args, **kwargs)

    st.markdown = _stripped
    return orig


def render_solar_farm_inline() -> None:
    """solar-farm has no main() — re-execute the script on each rerun."""
    try:
        solar_dir = str(_REPO_ROOT / "solar-farm")
        if solar_dir not in sys.path:
            sys.path.insert(0, solar_dir)

        orig_spc = _patch_spc()
        orig_md = _patch_markdown_strip_sidebar_css()
        try:
            runpy.run_path(
                str(_REPO_ROOT / "solar-farm" / "streamlit_app.py"),
                run_name="__main__",
            )
        finally:
            st.set_page_config = orig_spc
            st.markdown = orig_md
    except Exception as exc:
        _render_error("solar-farm", exc)
