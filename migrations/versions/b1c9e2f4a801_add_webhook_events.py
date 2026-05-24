"""add webhook_events

Revision ID: b1c9e2f4a801
Revises: acfa4339a289
Create Date: 2026-05-24 11:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'b1c9e2f4a801'
down_revision: Union[str, None] = 'acfa4339a289'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'webhook_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('provider', sa.String(20), nullable=False, server_default='paystack'),
        sa.Column('event_id', sa.String(128), nullable=False),
        sa.Column('event_type', sa.String(80), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='received'),
        sa.Column(
            'received_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        sa.Column('processed_at', sa.DateTime(timezone=True)),
        sa.Column('raw_payload', postgresql.JSONB),
        sa.Column('error_message', sa.Text),
    )
    op.create_unique_constraint(
        'uq_webhook_events_event_id',
        'webhook_events',
        ['event_id'],
    )
    op.create_index(
        'ix_webhook_events_event_type',
        'webhook_events',
        ['event_type'],
    )
    op.create_index(
        'ix_webhook_events_received_at',
        'webhook_events',
        ['received_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_webhook_events_received_at', table_name='webhook_events')
    op.drop_index('ix_webhook_events_event_type', table_name='webhook_events')
    op.drop_constraint('uq_webhook_events_event_id', 'webhook_events', type_='unique')
    op.drop_table('webhook_events')
