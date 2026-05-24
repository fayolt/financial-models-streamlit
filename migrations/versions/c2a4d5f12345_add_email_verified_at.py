"""add email_verified_at to users

Revision ID: c2a4d5f12345
Revises: b1c9e2f4a801
Create Date: 2026-05-24 11:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c2a4d5f12345'
down_revision: Union[str, None] = 'b1c9e2f4a801'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('users', 'email_verified_at')
