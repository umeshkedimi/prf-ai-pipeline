"""record llm_model and judge_model on eval_runs

Revision ID: c9f3a2b6e1d7
Revises: b7e2f1a4c8d5
Create Date: 2026-07-20 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9f3a2b6e1d7"
down_revision: Union[str, Sequence[str], None] = "b7e2f1a4c8d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Nullable on purpose: rows written before this migration were produced by an
    unknown model, and backfilling a guess would be worse than recording none.
    """
    op.add_column('eval_runs', sa.Column('llm_model', sa.String(length=100), nullable=True))
    op.add_column('eval_runs', sa.Column('judge_model', sa.String(length=100), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('eval_runs', 'judge_model')
    op.drop_column('eval_runs', 'llm_model')
