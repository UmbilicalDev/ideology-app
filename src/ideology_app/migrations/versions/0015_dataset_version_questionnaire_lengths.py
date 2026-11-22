"""Dataset Version questionnaire lengths (pipeline-statement-priority-tiers)

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-21 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0015'
down_revision: Union[str, Sequence[str], None] = '0014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Written by hand: one nullable JSON column and no data migration. Dataset
    # Versions are immutable, so every existing version keeps NULL (read as its
    # full length only). recreate='never' gives plain ALTER TABLE ... ADD COLUMN:
    # the table is never recreated, so the partial unique index
    # uq_dataset_versions_published_election_id keeps its WHERE clause and no
    # Statement is deleted by ON DELETE CASCADE.
    with op.batch_alter_table('dataset_versions', schema=None, recreate='never') as batch_op:
        batch_op.add_column(sa.Column('questionnaire_lengths', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # recreate='never': ALTER TABLE ... DROP COLUMN (SQLite >= 3.35), so every
    # Statement and the partial unique index survive.
    with op.batch_alter_table('dataset_versions', schema=None, recreate='never') as batch_op:
        batch_op.drop_column('questionnaire_lengths')
