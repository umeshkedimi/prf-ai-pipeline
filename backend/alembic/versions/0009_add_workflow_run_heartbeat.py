"""add workflow_runs.heartbeat_at

Revision ID: c8e4a1d6f203
Revises: a3c7e0f2b9d1
Create Date: 2026-10-04 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c8e4a1d6f203'
down_revision: Union[str, Sequence[str], None] = 'a3c7e0f2b9d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Nullable on purpose: rows from before this column have no heartbeat, and a
    # backfilled guess would make them look recently alive or long dead.
    op.add_column('workflow_runs', sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('workflow_runs', 'heartbeat_at')
