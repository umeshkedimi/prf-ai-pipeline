"""add pending_review to workflow_runs

Revision ID: f5770ad9a28c
Revises: e83355a87256
Create Date: 2026-07-18 21:46:01.106167

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f5770ad9a28c'
down_revision: Union[str, Sequence[str], None] = 'e83355a87256'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # NOTE: autogenerate also proposed dropping ix_donors_address_trgm/ix_donors_name_trgm
    # here — a false positive. Those GIN trgm indexes were created via raw op.execute()
    # in 0001 (not a SQLAlchemy Index() object), so autogenerate can't see them in the
    # models and assumes they're extraneous. They're real and still used by the CRM MCP
    # server's find_potential_duplicate_donors tool — intentionally left alone.
    op.add_column('workflow_runs', sa.Column('pending_review', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('workflow_runs', 'pending_review')
