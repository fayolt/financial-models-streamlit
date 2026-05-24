"""add file_data and inputs_json to report_runs for async background generation

Revision ID: e7f2a3b11111
Revises: e4f9b0c23456
Create Date: 2026-05-24 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e7f2a3b11111"
down_revision: Union[str, None] = "e4f9b0c23456"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Bytes for the generated report — written by background thread on success.
    op.add_column(
        "report_runs",
        sa.Column("file_data", sa.LargeBinary(), nullable=True),
    )
    # Serialised plugin inputs — enables a future worker process to reconstruct
    # the generation request without needing the objects in-process.
    op.add_column(
        "report_runs",
        sa.Column("inputs_json", postgresql.JSONB(), nullable=True),
    )
    # Composite index to make the polling query (user_id + status) fast.
    op.create_index(
        "ix_report_runs_user_status",
        "report_runs",
        ["user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_report_runs_user_status", table_name="report_runs")
    op.drop_column("report_runs", "inputs_json")
    op.drop_column("report_runs", "file_data")
