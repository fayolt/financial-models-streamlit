"""Unified Streamlit entry for the Zenkos financial-models SaaS.

Auth-gated: unauthenticated users see only login/signup pages; authenticated
users see the plugin pages plus their account.
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

from app.auth.cookie import get_session_token  # noqa: E402
from app.auth.service import get_current_user  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.pages import (  # noqa: E402
    account,
    admin_analytics,
    admin_users,
    forgot_password,
    login,
    pricing,
    reset_password,
    signup,
)
from app.plugin import SubscriptionTier, User as PluginUser, load_plugins  # noqa: E402


@st.cache_resource
def _registry():
    return load_plugins(_REPO_ROOT / "models")


st.set_page_config(
    page_title="Zenkos Financial Models",
    page_icon="📊",
    layout="wide",
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
if "reset_token" in st.query_params and "user" not in st.session_state:
    reset_password.render()
    st.stop()


if "user" not in st.session_state:
    pg = st.navigation([
        st.Page(login.render, title="Log in", url_path="login", icon=":material/login:"),
        st.Page(signup.render, title="Sign up", url_path="signup", icon=":material/person_add:"),
        st.Page(forgot_password.render, title="Forgot password", url_path="forgot-password", icon=":material/lock_reset:"),
    ])
else:
    user_dict = st.session_state.user
    plugin_user = PluginUser(
        id=UUID(user_dict["id"]),
        email=user_dict["email"],
        tier=SubscriptionTier(user_dict["tier"]),
    )

    def _make_page(plugin):
        def _page() -> None:
            plugin.render(user=plugin_user)
        _page.__name__ = f"render_{plugin.slug.replace('-', '_')}"
        return _page

    plugin_pages = []
    for plugin in _registry():
        title = f"{plugin.icon} {plugin.name}" if plugin.icon else plugin.name
        plugin_pages.append(
            st.Page(_make_page(plugin), title=title, url_path=plugin.slug)
        )

    account_page = st.Page(
        account.render, title="Account", url_path="account",
        icon=":material/account_circle:",
    )
    pricing_page = st.Page(
        pricing.render, title="Pricing", url_path="pricing",
        icon=":material/payments:",
    )

    nav: dict[str, list] = {
        "Models": plugin_pages,
        "Billing": [pricing_page, account_page],
    }
    if user_dict.get("is_admin"):
        nav["Admin"] = [
            st.Page(
                admin_users.render, title="Users", url_path="admin-users",
                icon=":material/group:",
            ),
            st.Page(
                admin_analytics.render, title="Analytics",
                url_path="admin-analytics", icon=":material/insights:",
            ),
        ]
    pg = st.navigation(nav)

pg.run()
