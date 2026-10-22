"""Mark Source Documents imported from a Source Text Bundle (bundle_file)

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-21 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0011'
down_revision: Union[str, Sequence[str], None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Written by hand: one nullable column, no backfill (null means "registered
    # with source add"). recreate='never' (plain ADD COLUMN): recreating
    # source_documents while PRAGMA foreign_keys=ON would delete every
    # source_document_pages row (ON DELETE CASCADE). The origin enum and the
    # source_url_matches_origin CHECK are unchanged.
    with op.batch_alter_table('source_documents', schema=None, recreate='never') as batch_op:
        batch_op.add_column(sa.Column('bundle_file', sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # recreate='never': ALTER TABLE ... DROP COLUMN (SQLite >= 3.35), so the
    # pages of every document survive.
    with op.batch_alter_table('source_documents', schema=None, recreate='never') as batch_op:
        batch_op.drop_column('bundle_file')
