"""The feedback_messages table as feedback-api created it with create_all.

Revision ID: f0001
Revises:
Create Date: 2026-10-29

A store made before feedback-admin already has this table; ``upgrade_schema``
stamps it at this revision instead of running it.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feedback_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "origin",
            sa.Enum(
                "landing",
                "results",
                name="feedback_origin",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("feedback_messages")
