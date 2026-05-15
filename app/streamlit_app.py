"""Unified Streamlit entry for the Zenkos financial-models SaaS.

Loads every registered plugin and exposes one page per model via st.navigation.
"""
from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID

# Streamlit runs this file directly, so the repo root must be on sys.path
# for `import app.plugin` to resolve.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import streamlit as st  # noqa: E402

from app.plugin import SubscriptionTier, User, load_plugins  # noqa: E402


@st.cache_resource
def _registry():
    return load_plugins(_REPO_ROOT / "models")


@st.cache_resource
def _dev_user() -> User:
    """Phase-0 stub user. Replaced by real auth in Phase 2."""
    return User(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        email="dev@zenkos.local",
        tier=SubscriptionTier.ENTERPRISE,
    )


st.set_page_config(
    page_title="Zenkos Financial Models",
    page_icon="📊",
    layout="wide",
)

registry = _registry()
user = _dev_user()


def _make_page(plugin):
    def _page() -> None:
        plugin.render(user=user)
    _page.__name__ = f"render_{plugin.slug.replace('-', '_')}"
    return _page


pages = []
for plugin in registry:
    title = f"{plugin.icon} {plugin.name}" if plugin.icon else plugin.name
    pages.append(
        st.Page(
            _make_page(plugin),
            title=title,
            url_path=plugin.slug,
        )
    )

pg = st.navigation(pages)
pg.run()
