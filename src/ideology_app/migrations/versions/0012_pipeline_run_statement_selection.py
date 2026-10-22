"""Record a Pipeline Run's Statement Selection (statement_selection)

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-22 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0012'
down_revision: Union[str, Sequence[str], None] = '0011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Written by hand: one nullable JSON column, no data migration (runs before
    # this revision keep a null value and the report shows "not recorded").
    # recreate='never' (plain ADD COLUMN): recreating pipeline_runs while
    # PRAGMA foreign_keys=ON would delete every Dataset Version (ON DELETE CASCADE).
    with op.batch_alter_table('pipeline_runs', schema=None, recreate='never') as batch_op:
        batch_op.add_column(sa.Column('statement_selection', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # recreate='never': ALTER TABLE ... DROP COLUMN (SQLite >= 3.35), so every
    # Dataset Version and its rows survive.
    with op.batch_alter_table('pipeline_runs', schema=None, recreate='never') as batch_op:
        batch_op.drop_column('statement_selection')
