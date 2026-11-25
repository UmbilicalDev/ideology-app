"""model_generation marker, Statement sources and Proposal Evidence (statements-from-proposals)

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-25 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0018'
down_revision: Union[str, Sequence[str], None] = '0017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _generation_column(table: str) -> sa.Column:
    # A VARCHAR(10) with one named column-level CHECK instead of sa.Enum: on
    # SQLite, Alembic skips (with a warning) the implicit CHECK of an Enum added
    # by ADD COLUMN, so the CHECK is spelled out. NOT NULL with a server default:
    # every existing run and Dataset Version reads 'legacy' (no UPDATE needed).
    return sa.Column(
        'model_generation',
        sa.String(length=10),
        sa.CheckConstraint(
            "model_generation IN ('legacy', 'v2')", name=op.f(f'ck_{table}_model_generation')
        ),
        nullable=False,
        server_default='legacy',
    )


def _add_generation(table: str) -> None:
    column = _generation_column(table)
    # recreate='never': plain ALTER TABLE ... ADD COLUMN. Neither table is
    # recreated, so no child row is deleted by ON DELETE CASCADE and the partial
    # unique index uq_dataset_versions_published_election_id keeps its WHERE.
    with op.batch_alter_table(table, schema=None, recreate='never') as batch_op:
        batch_op.add_column(column)


def upgrade() -> None:
    """Upgrade schema."""
    # Written by hand. Two new columns and two new, empty tables; no existing
    # table is recreated and no existing row changes.
    _add_generation('pipeline_runs')
    _add_generation('dataset_versions')
    op.create_table(
        'statement_proposals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('statement_id', sa.Integer(), nullable=False),
        sa.Column('rank', sa.Integer(), nullable=False),
        sa.Column('proposal_id', sa.Integer(), nullable=False),
        sa.CheckConstraint('rank >= 1', name=op.f('ck_statement_proposals_rank_positive')),
        sa.ForeignKeyConstraint(
            ['proposal_id'],
            ['proposals.id'],
            name=op.f('fk_statement_proposals_proposal_id_proposals'),
        ),
        sa.ForeignKeyConstraint(
            ['statement_id'],
            ['statements.id'],
            name=op.f('fk_statement_proposals_statement_id_statements'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_statement_proposals')),
        sa.UniqueConstraint(
            'statement_id', 'proposal_id',
            name=op.f('uq_statement_proposals_statement_id_proposal_id'),
        ),
        sa.UniqueConstraint(
            'statement_id', 'rank', name=op.f('uq_statement_proposals_statement_id_rank')
        ),
    )
    op.create_table(
        'party_position_proposals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('party_position_id', sa.Integer(), nullable=False),
        sa.Column('rank', sa.Integer(), nullable=False),
        sa.Column('proposal_id', sa.Integer(), nullable=False),
        sa.Column('source_document_id', sa.Integer(), nullable=False),
        sa.Column('constituencies', sa.JSON(), nullable=False),
        sa.CheckConstraint('rank >= 1', name=op.f('ck_party_position_proposals_rank_positive')),
        sa.ForeignKeyConstraint(
            ['party_position_id'],
            ['party_positions.id'],
            name=op.f('fk_party_position_proposals_party_position_id_party_positions'),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['proposal_id'],
            ['proposals.id'],
            name=op.f('fk_party_position_proposals_proposal_id_proposals'),
        ),
        sa.ForeignKeyConstraint(
            ['source_document_id'],
            ['source_documents.id'],
            name=op.f('fk_party_position_proposals_source_document_id_source_documents'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_party_position_proposals')),
        sa.UniqueConstraint(
            'party_position_id', 'proposal_id',
            name=op.f('uq_party_position_proposals_party_position_id_proposal_id'),
        ),
        sa.UniqueConstraint(
            'party_position_id', 'rank',
            name=op.f('uq_party_position_proposals_party_position_id_rank'),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('party_position_proposals')
    op.drop_table('statement_proposals')
    # recreate='never': ALTER TABLE ... DROP COLUMN (SQLite >= 3.35), so every
    # Dataset Version, Statement and Party Position survives.
    for table in ('dataset_versions', 'pipeline_runs'):
        with op.batch_alter_table(table, schema=None, recreate='never') as batch_op:
            batch_op.drop_column('model_generation')
