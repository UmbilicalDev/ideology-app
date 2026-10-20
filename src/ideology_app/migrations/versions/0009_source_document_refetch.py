"""Track URL re-fetches of Source Documents (replaced_by_id, last_checked_at)

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0009'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Written by hand: two nullable columns, no backfill (null means "never
    # checked" and "current"). replaced_by_id has no FOREIGN KEY: adding an FK
    # column on SQLite needs a table recreate, and recreating source_documents
    # while PRAGMA foreign_keys=ON would delete every source_document_pages row
    # (ON DELETE CASCADE). The re-fetch service keeps it consistent instead.
    with op.batch_alter_table('source_documents', schema=None, recreate='never') as batch_op:
        batch_op.add_column(sa.Column('replaced_by_id', sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    """Downgrade schema."""
    # recreate='never': ALTER TABLE ... DROP COLUMN (SQLite >= 3.35), so the
    # pages of every document survive.
    with op.batch_alter_table('source_documents', schema=None, recreate='never') as batch_op:
        batch_op.drop_column('last_checked_at')
        batch_op.drop_column('replaced_by_id')
