"""add llm_tokens counters to users

Revision ID: d3b6e7a45678
Revises: c2a4d5f12345
Create Date: 2026-05-24 11:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd3b6e7a45678'
down_revision: Union[str, None] = 'c2a4d5f12345'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column(
            'llm_tokens_this_month',
            sa.Integer,
            nullable=False,
            server_default='0',
        ),
    )
    op.add_column(
        'users',
        sa.Column(
            'llm_tokens_month_reset_at',
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.alter_column('users', 'llm_tokens_this_month', server_default=None)


def downgrade() -> None:
    op.drop_column('users', 'llm_tokens_month_reset_at')
    op.drop_column('users', 'llm_tokens_this_month')
