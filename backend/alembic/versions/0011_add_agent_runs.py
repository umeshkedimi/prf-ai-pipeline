"""add agent_runs and agent_steps

Revision ID: e5c1a8b30d27
Revises: d2b9f4a7c615
Create Date: 2026-10-07 15:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e5c1a8b30d27'
down_revision: Union[str, Sequence[str], None] = 'd2b9f4a7c615'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'agent_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('campaign_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('goal', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=20), server_default='running', nullable=False),
        sa.Column('budget', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('pending_approval', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('final_report', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_by_user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id']),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_agent_runs_campaign_id'), 'agent_runs', ['campaign_id'], unique=False)
    op.create_table(
        'agent_steps',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('agent_run_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('tool', sa.String(length=80), nullable=False),
        sa.Column('tier', sa.String(length=20), nullable=True),
        sa.Column('args', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('outcome', sa.String(length=20), nullable=False),
        sa.Column('observation', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['agent_run_id'], ['agent_runs.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('agent_run_id', 'seq', name='uq_agent_steps_run_seq'),
    )
    op.create_index(op.f('ix_agent_steps_agent_run_id'), 'agent_steps', ['agent_run_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_agent_steps_agent_run_id'), table_name='agent_steps')
    op.drop_table('agent_steps')
    op.drop_index(op.f('ix_agent_runs_campaign_id'), table_name='agent_runs')
    op.drop_table('agent_runs')
