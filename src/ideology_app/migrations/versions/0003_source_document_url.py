"""Add source_documents.source_url and its CHECK against origin.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Written by hand: autogenerate does not detect CHECKs on existing tables.
# Existing rows are all uploads, so a null source_url satisfies the CHECK.
SOURCE_URL_MATCHES_ORIGIN = (
    "(origin = 'url' AND source_url IS NOT NULL) "
    "OR (origin = 'upload' AND source_url IS NULL)"
)


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('source_documents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source_url', sa.String(length=2048), nullable=True))
        batch_op.create_check_constraint(
            op.f('ck_source_documents_source_url_matches_origin'),
            SOURCE_URL_MATCHES_ORIGIN,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('source_documents', schema=None) as batch_op:
        batch_op.drop_constraint(
            op.f('ck_source_documents_source_url_matches_origin'), type_='check'
        )
        batch_op.drop_column('source_url')
