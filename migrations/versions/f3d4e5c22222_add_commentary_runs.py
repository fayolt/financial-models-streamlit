"""add commentary_runs table for async LLM commentary generation

Revision ID: f3d4e5c22222
Revises: e7f2a3b11111
Create Date: 2026-05-24 13:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f3d4e5c22222"
down_revision: Union[str, None] = "e7f2a3b11111"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "commentary_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model_slug", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),  # pending|success|failed
        sa.Column("commentary_text", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_commentary_runs_user_status",
        "commentary_runs",
        ["user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_commentary_runs_user_status", table_name="commentary_runs")
    op.drop_table("commentary_runs")
