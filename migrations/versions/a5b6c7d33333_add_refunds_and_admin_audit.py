"""add refunds and admin_audit_log tables

Revision ID: a5b6c7d33333
Revises: f3d4e5c22222
Create Date: 2026-05-25 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a5b6c7d33333"
down_revision: Union[str, None] = "f3d4e5c22222"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── refunds ─────────────────────────────────────────────────────────────
    op.create_table(
        "refunds",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by_admin_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("paystack_transaction_reference", sa.String(120), nullable=False),
        sa.Column("paystack_refund_id", sa.String(120), nullable=True, unique=True),
        sa.Column("amount_minor_units", sa.Integer, nullable=True),  # None = full refund
        sa.Column("currency", sa.String(3), nullable=False, server_default="ZAR"),
        sa.Column("reason", sa.Text, nullable=False),
        # 'pending' | 'processed' | 'failed'
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_refunds_user_id", "refunds", ["user_id"])
    op.create_index(
        "ix_refunds_transaction_ref", "refunds", ["paystack_transaction_reference"]
    )

    # ── admin_audit_log ─────────────────────────────────────────────────────
    op.create_table(
        "admin_audit_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column(
            "target_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_admin_audit_log_actor_id", "admin_audit_log", ["actor_id"]
    )
    op.create_index(
        "ix_admin_audit_log_target_user", "admin_audit_log", ["target_user_id"]
    )
    op.create_index(
        "ix_admin_audit_log_created_at", "admin_audit_log", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_admin_audit_log_created_at", table_name="admin_audit_log")
    op.drop_index("ix_admin_audit_log_target_user", table_name="admin_audit_log")
    op.drop_index("ix_admin_audit_log_actor_id", table_name="admin_audit_log")
    op.drop_table("admin_audit_log")
    op.drop_index("ix_refunds_transaction_ref", table_name="refunds")
    op.drop_index("ix_refunds_user_id", table_name="refunds")
    op.drop_table("refunds")
