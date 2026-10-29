"""Add feedback_messages.reviewed_at, the Operator's reviewed mark (feedback-admin).

Revision ID: f0002
Revises: f0001
Create Date: 2026-10-29

Nullable, so every existing message stays and starts unreviewed. Added in place
(``recreate="never"``): the table is never copied.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f0002"
down_revision: Union[str, Sequence[str], None] = "f0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("feedback_messages", recreate="never") as batch:
        batch.add_column(sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("feedback_messages", recreate="never") as batch:
        batch.drop_column("reviewed_at")
