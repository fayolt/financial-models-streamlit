"""SQLAlchemy ORM models for the unified financial-models SaaS."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(
        String(254), unique=True, nullable=False, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(120))
    # 'free' | 'pro' | 'enterprise' — denormalised from the active subscription
    # for cheap gating reads; webhook handler keeps it in sync.
    tier: Mapped[str] = mapped_column(String(20), default="free", nullable=False)
    paystack_customer_id: Mapped[Optional[str]] = mapped_column(
        String(60), unique=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    # Lazy monthly counter — reset when month_reset_at < first-of-current-month.
    llm_tokens_this_month: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    llm_tokens_month_reset_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Hash of the JWT — never store the raw token. Used for revocation lookup.
    token_hash: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[Optional[str]] = mapped_column(String(500))


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    paystack_plan_code: Mapped[Optional[str]] = mapped_column(
        String(80), unique=True
    )
    monthly_price_minor_units: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="NGN", nullable=False)
    # None == unlimited
    monthly_report_quota: Mapped[Optional[int]] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id"), nullable=False
    )
    # 'active' | 'past_due' | 'cancelled' | 'incomplete'
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    paystack_subscription_code: Mapped[Optional[str]] = mapped_column(
        String(80), unique=True
    )
    current_period_start: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    current_period_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class ReportRun(Base):
    __tablename__ = "report_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model_slug: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    format: Mapped[str] = mapped_column(String(10), nullable=False)
    # 'pending' | 'success' | 'failed'
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    bytes_size: Mapped[Optional[int]] = mapped_column(Integer)
    storage_key: Mapped[Optional[str]] = mapped_column(String(255))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    # Async generation: raw bytes written by background thread on success.
    file_data: Mapped[Optional[bytes]] = mapped_column(LargeBinary)
    # Serialised inputs — lets a future worker reconstruct the job from DB alone.
    inputs_json: Mapped[Optional[dict]] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class AuthRateLimit(Base):
    """Per-IP attempt counter for brute-force protection on auth endpoints.

    Keyed by (ip, action, window_start) — one row per 5-minute window.
    Cleaned up lazily on each check.
    """

    __tablename__ = "auth_rate_limits"

    ip: Mapped[str] = mapped_column(Text, primary_key=True)
    action: Mapped[str] = mapped_column(String(20), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class CommentaryRun(Base):
    """Async LLM commentary generation job — mirrors ReportRun's state machine."""

    __tablename__ = "commentary_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model_slug: Mapped[str] = mapped_column(String(40), nullable=False)
    # 'pending' | 'success' | 'failed'
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    commentary_text: Mapped[Optional[str]] = mapped_column(Text)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class WebhookEvent(Base):
    """Dedup ledger for incoming webhook deliveries.

    `event_id` is a content hash of the raw request body — Paystack retries
    deliver the same body, so a UNIQUE constraint on this column gives us
    idempotency without trusting any specific field in the payload.
    """

    __tablename__ = "webhook_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="paystack")
    event_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    # 'received' | 'processed' | 'failed'
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="received")
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    raw_payload: Mapped[Optional[dict]] = mapped_column(JSONB)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
