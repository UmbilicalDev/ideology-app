"""Party logos: bytes, media type and SHA-256 on parties (party-logos-data)

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-26 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0013'
down_revision: Union[str, Sequence[str], None] = '0012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Written by hand: three nullable columns, no data migration (every Party
    # starts without a logo). "All three set or all null" is kept by the single
    # writer elections.set_party_logo, not by a CHECK: adding a table CHECK on
    # SQLite means recreating parties, and recreating it while
    # PRAGMA foreign_keys=ON would delete every child row (ON DELETE CASCADE).
    # recreate='never' gives plain ALTER TABLE ... ADD COLUMN.
    with op.batch_alter_table('parties', schema=None, recreate='never') as batch_op:
        batch_op.add_column(sa.Column('logo', sa.LargeBinary(), nullable=True))
        batch_op.add_column(sa.Column('logo_media_type', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('logo_sha256', sa.String(length=64), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # recreate='never': ALTER TABLE ... DROP COLUMN (SQLite >= 3.35), so every
    # Source Document, Party Position and other child row survives.
    with op.batch_alter_table('parties', schema=None, recreate='never') as batch_op:
        batch_op.drop_column('logo_sha256')
        batch_op.drop_column('logo_media_type')
        batch_op.drop_column('logo')
