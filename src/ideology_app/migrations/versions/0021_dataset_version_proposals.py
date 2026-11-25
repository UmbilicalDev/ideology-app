"""Frozen counted Proposals of v2 Dataset Versions (public-dataset-api-v2)

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-25 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0021'
down_revision: Union[str, Sequence[str], None] = '0020'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Written by hand. One new, empty, insert-only table; no existing table is
    # recreated or altered and no existing row changes (no backfill: every
    # Dataset Version before it is legacy).
    op.create_table(
        'dataset_version_proposals',
        sa.Column('dataset_version_id', sa.Integer(), nullable=False),
        sa.Column('party_id', sa.Integer(), nullable=False),
        sa.Column('rank', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('proposal_id', sa.Integer(), nullable=False),
        sa.Column('source_document_id', sa.Integer(), nullable=False),
        sa.Column('constituencies', sa.JSON(), nullable=False),
        sa.CheckConstraint('rank >= 1', name=op.f('ck_dataset_version_proposals_rank_positive')),
        sa.ForeignKeyConstraint(
            ['dataset_version_id'],
            ['dataset_versions.id'],
            name=op.f('fk_dataset_version_proposals_dataset_version_id_dataset_versions'),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['party_id'],
            ['parties.id'],
            name=op.f('fk_dataset_version_proposals_party_id_parties'),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['proposal_id'],
            ['proposals.id'],
            name=op.f('fk_dataset_version_proposals_proposal_id_proposals'),
        ),
        sa.ForeignKeyConstraint(
            ['source_document_id'],
            ['source_documents.id'],
            name=op.f('fk_dataset_version_proposals_source_document_id_source_documents'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint(
            'dataset_version_id', 'party_id', 'rank', name=op.f('pk_dataset_version_proposals')
        ),
        sa.UniqueConstraint(
            'dataset_version_id',
            'party_id',
            'proposal_id',
            name=op.f('uq_dataset_version_proposals_dataset_version_id_party_id_proposal_id'),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('dataset_version_proposals')
