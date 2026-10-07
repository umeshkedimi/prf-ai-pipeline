"""add campaign_donors and donor_imports.campaign_id

Revision ID: d2b9f4a7c615
Revises: c8e4a1d6f203
Create Date: 2026-10-07 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd2b9f4a7c615'
down_revision: Union[str, Sequence[str], None] = 'c8e4a1d6f203'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'campaign_donors',
        sa.Column('campaign_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('donor_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('import_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='staged', nullable=False),
        sa.Column('status_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id']),
        sa.ForeignKeyConstraint(['donor_id'], ['donors.id']),
        sa.ForeignKeyConstraint(['import_id'], ['donor_imports.id']),
        sa.PrimaryKeyConstraint('campaign_id', 'donor_id'),
    )
    op.create_index(op.f('ix_campaign_donors_donor_id'), 'campaign_donors', ['donor_id'], unique=False)
    # Nullable: uploads from before campaigns-as-membership have no campaign.
    op.add_column('donor_imports', sa.Column('campaign_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('fk_donor_imports_campaign_id', 'donor_imports', 'campaigns', ['campaign_id'], ['id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_donor_imports_campaign_id', 'donor_imports', type_='foreignkey')
    op.drop_column('donor_imports', 'campaign_id')
    op.drop_index(op.f('ix_campaign_donors_donor_id'), table_name='campaign_donors')
    op.drop_table('campaign_donors')
