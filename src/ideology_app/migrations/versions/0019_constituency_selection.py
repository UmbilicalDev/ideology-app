"""Per-Constituency rows of v2 Dataset Versions (constituency-selection-validation)

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-25 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0019'
down_revision: Union[str, Sequence[str], None] = '0018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_REASONS = "'fewer_than_two_parties', 'too_few_statements', 'low_party_coverage'"
_EXCLUSIONS = "'no_manifesto', 'discarded_at_review', 'too_few_proposals'"


def upgrade() -> None:
    """Upgrade schema."""
    # Written by hand. Three new, empty, insert-only tables; no existing table is
    # recreated or altered and no existing row changes. Reason columns are
    # VARCHAR with one named CHECK, not sa.Enum.
    op.create_table(
        'dataset_version_constituencies',
        sa.Column('dataset_version_id', sa.Integer(), nullable=False),
        sa.Column('constituency_code', sa.String(length=2), nullable=False),
        sa.Column('available', sa.Boolean(), nullable=False),
        sa.Column('unavailable_reason', sa.String(length=30), nullable=True),
        sa.Column('valid_statement_count', sa.Integer(), nullable=False),
        sa.Column('offered_lengths', sa.JSON(), nullable=False),
        sa.Column('detail', sa.JSON(), nullable=True),
        sa.CheckConstraint(
            'valid_statement_count >= 0',
            name=op.f('ck_dataset_version_constituencies_count_nonnegative'),
        ),
        sa.CheckConstraint(
            # IS NOT NULL: without it a NULL reason makes the IN test NULL and
            # the CHECK would pass for an unavailable row with no reason.
            f'(available AND unavailable_reason IS NULL) OR (NOT available AND '
            f'unavailable_reason IS NOT NULL AND unavailable_reason IN ({_REASONS}))',
            name=op.f('ck_dataset_version_constituencies_reason_matches_available'),
        ),
        sa.ForeignKeyConstraint(
            ['constituency_code'],
            ['constituencies.code'],
            name=op.f('fk_dataset_version_constituencies_constituency_code_constituencies'),
        ),
        sa.ForeignKeyConstraint(
            ['dataset_version_id'],
            ['dataset_versions.id'],
            name=op.f('fk_dataset_version_constituencies_dataset_version_id_dataset_versions'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint(
            'dataset_version_id', 'constituency_code',
            name=op.f('pk_dataset_version_constituencies'),
        ),
    )
    op.create_table(
        'dataset_version_candidatures',
        sa.Column('dataset_version_id', sa.Integer(), nullable=False),
        sa.Column('party_id', sa.Integer(), nullable=False),
        sa.Column('constituency_code', sa.String(length=2), nullable=False),
        sa.Column('excluded_reason', sa.String(length=30), nullable=True),
        sa.CheckConstraint(
            f'excluded_reason IS NULL OR excluded_reason IN ({_EXCLUSIONS})',
            name=op.f('ck_dataset_version_candidatures_excluded_reason_known'),
        ),
        sa.ForeignKeyConstraint(
            ['constituency_code'],
            ['constituencies.code'],
            name=op.f('fk_dataset_version_candidatures_constituency_code_constituencies'),
        ),
        sa.ForeignKeyConstraint(
            ['dataset_version_id'],
            ['dataset_versions.id'],
            name=op.f('fk_dataset_version_candidatures_dataset_version_id_dataset_versions'),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['party_id'],
            ['parties.id'],
            name=op.f('fk_dataset_version_candidatures_party_id_parties'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint(
            'dataset_version_id', 'party_id', 'constituency_code',
            name=op.f('pk_dataset_version_candidatures'),
        ),
    )
    op.create_table(
        'constituency_statements',
        sa.Column('dataset_version_id', sa.Integer(), nullable=False),
        sa.Column('constituency_code', sa.String(length=2), nullable=False),
        sa.Column('rank', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('statement_id', sa.Integer(), nullable=False),
        sa.CheckConstraint('rank >= 1', name=op.f('ck_constituency_statements_rank_positive')),
        sa.ForeignKeyConstraint(
            ['constituency_code'],
            ['constituencies.code'],
            name=op.f('fk_constituency_statements_constituency_code_constituencies'),
        ),
        sa.ForeignKeyConstraint(
            ['dataset_version_id'],
            ['dataset_versions.id'],
            name=op.f('fk_constituency_statements_dataset_version_id_dataset_versions'),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['statement_id'],
            ['statements.id'],
            name=op.f('fk_constituency_statements_statement_id_statements'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint(
            'dataset_version_id', 'constituency_code', 'rank',
            name=op.f('pk_constituency_statements'),
        ),
        sa.UniqueConstraint(
            'dataset_version_id', 'constituency_code', 'statement_id',
            name=op.f('uq_constituency_statements_dataset_version_id_constituency_code_statement_id'),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('constituency_statements')
    op.drop_table('dataset_version_candidatures')
    op.drop_table('dataset_version_constituencies')
