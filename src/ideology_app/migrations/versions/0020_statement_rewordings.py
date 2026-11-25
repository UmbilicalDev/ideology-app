"""Applied Statement Rewordings of v2 Statements (statement-rewording)

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-25 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0020'
down_revision: Union[str, Sequence[str], None] = '0019'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Written by hand. One new, empty, insert-only table; no existing table is
    # recreated or altered (``statements`` is referenced with ON DELETE CASCADE,
    # so a batch rebuild of it is avoided) and no existing row changes.
    op.create_table(
        'statement_rewordings',
        sa.Column('statement_id', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('ai_text', sa.String(length=300), nullable=False),
        sa.Column('reason', sa.String(length=500), nullable=False),
        sa.Column('explanation', sa.String(length=500), nullable=False),
        sa.CheckConstraint(
            "trim(reason) <> ''", name=op.f('ck_statement_rewordings_reason_not_blank')
        ),
        sa.ForeignKeyConstraint(
            ['statement_id'],
            ['statements.id'],
            name=op.f('fk_statement_rewordings_statement_id_statements'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('statement_id', name=op.f('pk_statement_rewordings')),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('statement_rewordings')
