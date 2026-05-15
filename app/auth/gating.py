"""Subscription-tier gating helpers."""
from __future__ import annotations

from functools import wraps
from typing import Callable, TypeVar

import streamlit as st

from app.plugin.contract import SubscriptionTier

_TIER_ORDER: dict[SubscriptionTier, int] = {
    SubscriptionTier.FREE: 0,
    SubscriptionTier.PRO: 1,
    SubscriptionTier.ENTERPRISE: 2,
}

F = TypeVar("F", bound=Callable[..., object])


def user_meets_tier(user_tier: str, required: SubscriptionTier) -> bool:
    try:
        return _TIER_ORDER[SubscriptionTier(user_tier)] >= _TIER_ORDER[required]
    except (KeyError, ValueError):
        return False


def requires_tier(required: SubscriptionTier) -> Callable[[F], F]:
    """Decorator that gates a render function on the current user's tier.

    Expects st.session_state.user to be set (a dict with a 'tier' key); the
    streamlit_app entry only renders gated pages once auth has hydrated state.
    """
    def decorator(fn: F) -> F:
        @wraps(fn)
        def wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
            user = st.session_state.get("user")
            if user is None:
                st.error("You must be logged in to view this page.")
                return None
            if not user_meets_tier(user["tier"], required):
                st.warning(
                    f"This feature requires the **{required.value.title()}** tier. "
                    f"You're currently on **{user['tier'].title()}**."
                )
                st.info("Upgrade from the Account page.")
                return None
            return fn(*args, **kwargs)
        return wrapper  # type: ignore[return-value]
    return decorator
