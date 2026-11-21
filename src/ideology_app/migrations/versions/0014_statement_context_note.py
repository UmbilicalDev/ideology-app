"""Statement context notes and the run's anchor Dataset Version (pipeline-statement-clarity-context)

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-21 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0014'
down_revision: Union[str, Sequence[str], None] = '0013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Written by hand: two nullable columns and no data migration. Dataset
    # Versions are immutable, so every existing Statement keeps a NULL note and
    # every existing run a NULL anchor version. No FOREIGN KEY on
    # anchor_dataset_version_id (like resumed_from_run_id): adding one on SQLite
    # needs a table recreate, and recreating pipeline_runs or statements while
    # PRAGMA foreign_keys=ON would delete every child row (ON DELETE CASCADE).
    # recreate='never' gives plain ALTER TABLE ... ADD COLUMN.
    with op.batch_alter_table('statements', schema=None, recreate='never') as batch_op:
        batch_op.add_column(sa.Column('context_note', sa.String(length=500), nullable=True))
    with op.batch_alter_table('pipeline_runs', schema=None, recreate='never') as batch_op:
        batch_op.add_column(sa.Column('anchor_dataset_version_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # recreate='never': ALTER TABLE ... DROP COLUMN (SQLite >= 3.35), so every
    # Party Position, Validation result and other child row survives.
    with op.batch_alter_table('pipeline_runs', schema=None, recreate='never') as batch_op:
        batch_op.drop_column('anchor_dataset_version_id')
    with op.batch_alter_table('statements', schema=None, recreate='never') as batch_op:
        batch_op.drop_column('context_note')
