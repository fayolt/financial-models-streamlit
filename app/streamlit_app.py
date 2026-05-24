"""Unified Streamlit entry for the Numquants financial-models SaaS.

Auth-gated: unauthenticated users see only login/signup pages; authenticated
users see the Dashboard (models grid) plus per-model landing pages.
"""
from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID

# Streamlit runs this file directly, so the repo root must be on sys.path.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import streamlit as st  # noqa: E402

import logging  # noqa: E402
import uuid as _uuid_mod  # noqa: E402

from app.config import (  # noqa: E402
    log_startup_summary,
    validate_for_web,
)
from app.logging_setup import configure_logging  # noqa: E402

# JSON logs to stdout for DO/Datadog ingestion. Must run before anything
# else logs so the format is consistent.
configure_logging("web")

# Fail loud on missing/placeholder secrets in production.
validate_for_web()

from app.auth.cookie import get_session_token  # noqa: E402
from app.auth.service import get_current_user  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.pages import (  # noqa: E402
    account,
    admin_analytics,
    admin_users,
    forgot_password,
    login,
    model_landing,
    model_workspace,
    models_dashboard,
    pricing,
    reset_password,
    signup,
    verify_email,
)
from app.pages.account import (  # noqa: E402
    _handle_paystack_callback as _process_paystack_callback,
)
from app.plugin import SubscriptionTier, User as PluginUser, load_plugins  # noqa: E402

log_startup_summary("web")

_log = logging.getLogger("app.streamlit")


def _is_streamlit_control_flow(exc: BaseException) -> bool:
    """Recognise Streamlit's RerunException/StopException across versions
    without coupling to its internal import paths."""
    return type(exc).__name__ in {"RerunException", "StopException"}


def _run_with_error_boundary(fn, *args, **kwargs):
    """Run `fn` and surface a friendly error if it raises, logging the full
    traceback with a correlation UUID so we can grep the JSON logs."""
    try:
        return fn(*args, **kwargs)
    except BaseException as exc:
        if _is_streamlit_control_flow(exc):
            raise
        error_id = _uuid_mod.uuid4().hex[:12]
        _log.exception("page rendering failed", extra={"error_id": error_id})
        st.error(
            "Something went wrong while loading this page. Our team has been "
            f"notified.\n\nReference: `{error_id}`"
        )
        st.stop()


# --- Config: which model slugs are "ready" today vs. "in coming" -------------
# Listed as "Available models" in the sidebar / dashboard. Plugins not in this
# set are surfaced under "In coming" — registered as pages (so URLs work) but
# shown with a Coming-soon placeholder when visited.
_AVAILABLE_SLUGS: set[str] = {
    "biotech",
    "cassava-ethanol",
    "chicken-farming",
    "goat-farming",
    "microbrewery",
    "pharma",
    "solar-farm",
}


def _gated_renderer(renderer, plugin, plugin_user) -> None:
    """Run renderer() with every st.download_button call tier-gated.

    Patches st.download_button before the native workspace renders and
    restores it afterward (same pattern as the set_page_config patch).

    Tier rules: Free → no downloads; Pro → XLSX/CSV; Enterprise → all formats.
    Each successful download is audited in report_runs for quota tracking.
    """
    from app.db.models import ReportRun  # local to avoid circular import at load time
    from app.plugin.contract import Format
    from app.reports.service import FORMAT_TIER_REQUIRED, can_generate, quota_remaining

    user_tier = plugin_user.tier.value
    user_id = plugin_user.id

    with SessionLocal() as db:
        remaining = quota_remaining(db, user_id)

    _EXT_TO_FMT: dict[str, Format] = {
        "xlsx": Format.XLSX,
        "xls": Format.XLSX,
        "pdf": Format.PDF,
        "docx": Format.DOCX,
        "csv": Format.CSV,
    }
    orig_dl = st.download_button

    def _gated(*args, **kwargs):
        label = (args[0] if args else None) or kwargs.get("label", "Download")
        data = args[1] if len(args) > 1 else kwargs.get("data", b"")
        file_name = (args[2] if len(args) > 2 else None) or kwargs.get("file_name") or ""
        key = kwargs.get("key")
        use_cw = kwargs.get("use_container_width", False)

        ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        fmt = _EXT_TO_FMT.get(ext)
        # Derive a stable key for the replacement button so Streamlit doesn't
        # complain about duplicate widget IDs across reruns.
        gated_key = f"_locked_{key}" if key else f"_locked_{abs(hash(label + file_name))}"

        if fmt and not can_generate(user_tier=user_tier, fmt=fmt):
            required = FORMAT_TIER_REQUIRED.get(fmt, SubscriptionTier.ENTERPRISE)
            st.button(
                f"🔒 {label}",
                disabled=True,
                help=f"Upgrade to {required.value.title()} to enable {ext.upper()} downloads.",
                key=gated_key,
                use_container_width=use_cw,
            )
            return False

        if remaining is not None and remaining <= 0:
            st.button(
                f"📊 {label} (quota exceeded)",
                disabled=True,
                help="Monthly report quota exhausted. Upgrade to Enterprise for unlimited exports.",
                key=gated_key,
                use_container_width=use_cw,
            )
            return False

        clicked = orig_dl(*args, **kwargs)
        if clicked and fmt:
            # Audit the download so quota_remaining() counts it next render.
            try:
                raw = data() if callable(data) else data
                size = len(raw) if isinstance(raw, (bytes, bytearray)) else None
                with SessionLocal() as db:
                    db.add(ReportRun(
                        user_id=user_id,
                        model_slug=plugin.slug,
                        format=ext,
                        status="success",
                        bytes_size=size,
                    ))
                    db.commit()
            except Exception:
                pass  # never block a download over an audit failure
        return clicked

    st.download_button = _gated
    try:
        renderer()
    finally:
        st.download_button = orig_dl


@st.cache_resource
def _registry():
    return load_plugins(_REPO_ROOT / "models")


st.set_page_config(
    page_title="Numquants Financial Models",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _hydrate_user_from_cookie() -> None:
    """Populate st.session_state.user from the persisted cookie, if any."""
    if "user" in st.session_state:
        return
    token = get_session_token()
    if not token:
        return
    with SessionLocal() as db:
        user = get_current_user(db, token)
    if user is None:
        return
    st.session_state.user = {
        "id": str(user.id),
        "email": user.email,
        "tier": user.tier,
        "full_name": user.full_name,
        "is_admin": user.is_admin,
    }
    st.session_state.session_token = token


_hydrate_user_from_cookie()


# Reset-password flow uses a special URL routed by ?reset_token=… in the
# query string. It bypasses normal navigation so an unauthenticated visitor
# arriving from an emailed link lands directly on the form.
if (
    ("reset_token" in st.query_params or "_reset_token" in st.session_state)
    and "user" not in st.session_state
):
    _run_with_error_boundary(reset_password.render)
    st.stop()


# Email-verification flow uses ?verify_email_token=… in the query string.
# Run before navigation so the link lands directly on the verification page.
if "verify_email_token" in st.query_params:
    _run_with_error_boundary(verify_email.render)
    st.stop()


# Paystack redirects back to *some* URL after checkout — which may or may
# not be /account depending on plan/dashboard config. Detect ?reference= or
# ?trxref= at the top level so the callback runs no matter where Paystack
# lands the user. Inline `st.success` will appear above the default page.
if (
    "user" in st.session_state
    and ("reference" in st.query_params or "trxref" in st.query_params)
):
    _run_with_error_boundary(_process_paystack_callback)


if "user" not in st.session_state:
    pg = st.navigation([
        st.Page(login.render, title="Log in", url_path="login", icon=":material/login:"),
        st.Page(signup.render, title="Sign up", url_path="signup", icon=":material/person_add:"),
        st.Page(forgot_password.render, title="Forgot password", url_path="forgot-password", icon=":material/lock_reset:"),
    ])
    _run_with_error_boundary(pg.run)
else:
    user_dict = st.session_state.user

    # Refresh tier from DB on every page load so a webhook-driven demotion
    # (cancellation, payment failure) takes effect immediately instead of
    # waiting up to SESSION_TTL_SECONDS (30 days) for the user to log in
    # again. One indexed PK lookup per script run — negligible.
    from app.db.models import User as _DbUser  # noqa: E402

    with SessionLocal() as _db:
        _fresh = _db.get(_DbUser, UUID(user_dict["id"]))
        if _fresh is not None and _fresh.is_active:
            if user_dict.get("tier") != _fresh.tier:
                user_dict["tier"] = _fresh.tier
                st.session_state.user = user_dict
        else:
            # User was deleted/deactivated; force re-login.
            st.session_state.pop("user", None)
            st.session_state.pop("session_token", None)
            st.rerun()

    plugin_user = PluginUser(
        id=UUID(user_dict["id"]),
        email=user_dict["email"],
        tier=SubscriptionTier(user_dict["tier"]),
    )

    registry = _registry()
    all_plugins = sorted(registry, key=lambda p: p.name)
    available_plugins = [p for p in all_plugins if p.slug in _AVAILABLE_SLUGS]
    coming_plugins = [p for p in all_plugins if p.slug not in _AVAILABLE_SLUGS]

    # --- Build per-plugin pages ---------------------------------------------
    # Each page wraps the plugin in a landing-then-workspace flow:
    #   * coming-soon plugins → static Coming-soon placeholder
    #   * available plugins → landing page first (template + Create button);
    #     after Create, switch to the plugin's actual render() (the existing
    #     compute + download view from the contract).

    # Workspace renderers — what shows after the user clicks Create model.
    # All 7 models now use Option C (inline import).
    _WORKSPACE_RENDERERS = {
        "biotech":          model_workspace.render_biotech_inline,
        "cassava-ethanol":  model_workspace.render_cassava_ethanol_inline,
        "chicken-farming":  model_workspace.render_chicken_farming_inline,
        "goat-farming":     model_workspace.render_goat_farming_inline,
        "microbrewery":     model_workspace.render_microbrewery_inline,
        "pharma":           model_workspace.render_pharma_inline,
        "solar-farm":       model_workspace.render_solar_farm_inline,
    }

    def _make_plugin_page(plugin):
        is_available = plugin.slug in _AVAILABLE_SLUGS

        def _page() -> None:
            if not is_available:
                model_landing.render_coming_soon(plugin)
                return
            if model_landing.is_started(plugin.slug):
                # Back button to return to landing
                back_col, _ = st.columns([1, 11])
                with back_col:
                    if st.button("← Back", key=f"back-{plugin.slug}"):
                        model_landing.mark_not_started(plugin.slug)
                        st.rerun()
                renderer = _WORKSPACE_RENDERERS.get(plugin.slug)
                if renderer is not None:
                    _gated_renderer(renderer, plugin, plugin_user)
                else:
                    plugin.render(user=plugin_user)
            else:
                model_landing.render(plugin)

        _page.__name__ = f"render_{plugin.slug.replace('-', '_')}"
        return _page

    plugin_page_objs: dict[str, st.Page] = {}
    for plugin in all_plugins:
        title = f"{plugin.icon} {plugin.name}" if plugin.icon else plugin.name
        plugin_page_objs[plugin.slug] = st.Page(
            _make_plugin_page(plugin),
            title=title,
            url_path=plugin.slug,
        )

    # --- Dashboard page (default) ------------------------------------------

    def _on_select_from_dashboard(slug: str) -> None:
        model_landing.mark_not_started(slug)  # reset "started" → land on the landing page
        st.switch_page(plugin_page_objs[slug])

    def _dashboard_page() -> None:
        models_dashboard.render(available_plugins, _on_select_from_dashboard)

    dashboard_page = st.Page(
        _dashboard_page,
        title="Dashboard",
        url_path="dashboard",
        icon=":material/dashboard:",
        default=True,
    )

    # --- Billing + Admin pages ----------------------------------------------
    account_page = st.Page(
        account.render, title="Account", url_path="account",
        icon=":material/account_circle:",
    )
    pricing_page = st.Page(
        pricing.render, title="Pricing", url_path="pricing",
        icon=":material/payments:",
    )
    admin_pages: list[st.Page] = []
    if user_dict.get("is_admin"):
        admin_pages = [
            st.Page(
                admin_users.render, title="Users", url_path="admin-users",
                icon=":material/group:",
            ),
            st.Page(
                admin_analytics.render, title="Analytics",
                url_path="admin-analytics", icon=":material/insights:",
            ),
        ]

    # --- Custom sidebar (replaces Streamlit's default nav rendering) --------
    with st.sidebar:
        st.markdown(
            "<h2 style='margin:0 0 16px 0;'>"
            "<span style='color:#16a34a;'>●</span> NumQuants"
            "</h2>",
            unsafe_allow_html=True,
        )

        st.markdown("**HOME**")
        if st.button(
            "🏠  Dashboard",
            key="sidebar-dashboard",
            use_container_width=True,
        ):
            st.switch_page(dashboard_page)

        st.markdown(f"**AVAILABLE MODELS ({len(available_plugins)})**")
        for plugin in available_plugins:
            label = (
                f"{plugin.icon}  {plugin.name}" if plugin.icon else plugin.name
            )
            if st.button(
                label,
                key=f"sidebar-{plugin.slug}",
                use_container_width=True,
            ):
                st.switch_page(plugin_page_objs[plugin.slug])

        if coming_plugins:
            st.markdown(f"**COMING SOON ({len(coming_plugins)})**")
            for plugin in coming_plugins:
                label = (
                    f"{plugin.icon}  {plugin.name}" if plugin.icon else plugin.name
                )
                # Disabled — visual placeholder only.
                st.button(
                    label,
                    key=f"sidebar-coming-{plugin.slug}",
                    use_container_width=True,
                    disabled=True,
                )

        st.markdown("**BILLING**")
        if st.button(
            "💳  Pricing", key="sidebar-pricing", use_container_width=True
        ):
            st.switch_page(pricing_page)
        if st.button(
            "👤  Account", key="sidebar-account", use_container_width=True
        ):
            st.switch_page(account_page)

        if admin_pages:
            st.markdown("**ADMIN**")
            if st.button(
                "👥  Users", key="sidebar-admin-users", use_container_width=True
            ):
                st.switch_page(admin_pages[0])
            if st.button(
                "📈  Analytics",
                key="sidebar-admin-analytics",
                use_container_width=True,
            ):
                st.switch_page(admin_pages[1])

    # --- Hidden nav: still gives us URL routing without showing the default
    # sidebar list (we render our own above). ---
    pg = st.navigation(
        [dashboard_page, *plugin_page_objs.values(), pricing_page, account_page, *admin_pages],
        position="hidden",
    )
    _run_with_error_boundary(pg.run)
