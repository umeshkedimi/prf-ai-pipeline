"""record token counts on agent_audit_log

Revision ID: d4b8e6c02f19
Revises: c9f3a2b6e1d7
Create Date: 2026-07-20 13:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd4b8e6c02f19'
down_revision: Union[str, Sequence[str], None] = 'c9f3a2b6e1d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Nullable: rows written before this migration have no token data, and zero
    would read as "this step was free" rather than "this was never measured".
    """
    op.add_column('agent_audit_log', sa.Column('input_tokens', sa.Integer(), nullable=True))
    op.add_column('agent_audit_log', sa.Column('output_tokens', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('agent_audit_log', 'output_tokens')
    op.drop_column('agent_audit_log', 'input_tokens')
