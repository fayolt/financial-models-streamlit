"""add auth_rate_limits table for IP-based brute-force protection

Revision ID: e4f9b0c23456
Revises: d3b6e7a45678
Create Date: 2026-05-24 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e4f9b0c23456"
down_revision: Union[str, None] = "d3b6e7a45678"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "auth_rate_limits",
        sa.Column("ip", sa.Text(), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("ip", "action", "window_start"),
    )
    op.create_index(
        "ix_auth_rate_limits_window_start",
        "auth_rate_limits",
        ["window_start"],
    )


def downgrade() -> None:
    op.drop_index("ix_auth_rate_limits_window_start", table_name="auth_rate_limits")
    op.drop_table("auth_rate_limits")
