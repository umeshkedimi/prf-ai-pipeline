"""add eval_runs for evaluation history

Revision ID: b7e2f1a4c8d5
Revises: a1c4e7d90b23
Create Date: 2026-07-19 16:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b7e2f1a4c8d5'
down_revision: Union[str, Sequence[str], None] = 'a1c4e7d90b23'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'eval_runs',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('suite', sa.String(length=50), nullable=False),
        sa.Column('git_sha', sa.String(length=40), nullable=True),
        sa.Column('runs_per_case', sa.Integer(), nullable=False),
        sa.Column('case_count', sa.Integer(), nullable=False),
        sa.Column('duration_s', sa.Float(), nullable=False),
        sa.Column('report', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('run_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_eval_runs_suite'), 'eval_runs', ['suite'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_eval_runs_suite'), table_name='eval_runs')
    op.drop_table('eval_runs')
