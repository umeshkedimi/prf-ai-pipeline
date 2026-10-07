"""add agent_runs.heartbeat_at

Revision ID: f7a2d9c41b83
Revises: e5c1a8b30d27
Create Date: 2026-10-07 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f7a2d9c41b83'
down_revision: Union[str, Sequence[str], None] = 'e5c1a8b30d27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Nullable: rows from before this column have no heartbeat, and a backfilled guess
    # would make them look recently alive or long dead (same reasoning as
    # workflow_runs.heartbeat_at).
    op.add_column('agent_runs', sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('agent_runs', 'heartbeat_at')
