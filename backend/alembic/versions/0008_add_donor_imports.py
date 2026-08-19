"""add donor_imports table

Revision ID: a3c7e0f2b9d1
Revises: f1a7c93b5e02
Create Date: 2026-08-19 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a3c7e0f2b9d1'
down_revision: Union[str, Sequence[str], None] = 'f1a7c93b5e02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'donor_imports',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('uploaded_by_user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('rows_inserted', sa.Integer(), nullable=False),
        sa.Column('rows_updated', sa.Integer(), nullable=False),
        sa.Column('rows_rejected', sa.Integer(), nullable=False),
        sa.Column('rejected_rows', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['uploaded_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_donor_imports_uploaded_by_user_id'), 'donor_imports', ['uploaded_by_user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_donor_imports_uploaded_by_user_id'), table_name='donor_imports')
    op.drop_table('donor_imports')
