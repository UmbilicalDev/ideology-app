"""Proposal extractions, their recorded calls and Proposals (proposal-extraction)

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0017'
down_revision: Union[str, Sequence[str], None] = '0016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Written by hand. Three new, empty tables; no existing table changes. The
    # foreign keys have no ON DELETE CASCADE: Proposals and calls are never
    # deleted (only the calls of an in_progress extraction, by --restart, which
    # deletes them explicitly before the extraction row).
    op.create_table(
        'proposal_extractions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column(
            'status',
            sa.Enum(
                'in_progress',
                'complete',
                name='proposal_extraction_status',
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column('llm_provider', sa.String(length=50), nullable=False),
        sa.Column('llm_model', sa.String(length=200), nullable=False),
        sa.Column('prompt_version', sa.String(length=20), nullable=False),
        sa.Column('chunk_max_chars', sa.Integer(), nullable=False),
        sa.Column('chunk_count', sa.Integer(), nullable=False),
        sa.Column('check_version', sa.String(length=20), nullable=False),
        sa.Column('validated_count', sa.Integer(), nullable=True),
        sa.Column('report', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_proposal_extractions')),
        sa.UniqueConstraint('content_hash', name=op.f('uq_proposal_extractions_content_hash')),
    )
    op.create_table(
        'proposal_extraction_calls',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('extraction_id', sa.Integer(), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('first_page', sa.Integer(), nullable=False),
        sa.Column('last_page', sa.Integer(), nullable=False),
        sa.Column('request_hash', sa.String(length=64), nullable=False),
        sa.Column('output', sa.JSON(), nullable=False),
        sa.Column('input_tokens', sa.Integer(), nullable=False),
        sa.Column('output_tokens', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['extraction_id'],
            ['proposal_extractions.id'],
            name=op.f('fk_proposal_extraction_calls_extraction_id_proposal_extractions'),
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_proposal_extraction_calls')),
        sa.UniqueConstraint(
            'extraction_id',
            'chunk_index',
            name=op.f('uq_proposal_extraction_calls_extraction_id_chunk_index'),
        ),
    )
    op.create_table(
        'proposals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('extraction_id', sa.Integer(), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('page', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('categories', sa.JSON(), nullable=False),
        sa.Column('tags', sa.JSON(), nullable=False),
        sa.CheckConstraint('page >= 1', name=op.f('ck_proposals_page_positive')),
        sa.ForeignKeyConstraint(
            ['extraction_id'],
            ['proposal_extractions.id'],
            name=op.f('fk_proposals_extraction_id_proposal_extractions'),
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_proposals')),
        sa.UniqueConstraint(
            'extraction_id', 'ordinal', name=op.f('uq_proposals_extraction_id_ordinal')
        ),
    )
    with op.batch_alter_table('proposals', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_proposals_content_hash'), ['content_hash'], unique=False
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('proposals', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_proposals_content_hash'))
    op.drop_table('proposals')
    op.drop_table('proposal_extraction_calls')
    op.drop_table('proposal_extractions')
