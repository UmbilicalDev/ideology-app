"""Record each LLM call of a Pipeline Run and the run it resumes from

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-21 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0010'
down_revision: Union[str, Sequence[str], None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Written by hand: a new insert-only table and one nullable column, no
    # backfill (older runs have no recorded calls and resume from nothing).
    # resumed_from_run_id has no FOREIGN KEY: adding an FK column on SQLite
    # needs a table recreate, and recreating pipeline_runs while PRAGMA
    # foreign_keys=ON would cascade-delete every Dataset Version.
    op.create_table(
        'pipeline_run_calls',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('pipeline_run_id', sa.Integer(), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('task', sa.String(length=50), nullable=False),
        sa.Column('request_hash', sa.String(length=64), nullable=False),
        sa.Column('output', sa.JSON(), nullable=False),
        sa.Column('input_tokens', sa.Integer(), nullable=False),
        sa.Column('output_tokens', sa.Integer(), nullable=False),
        sa.Column('reused', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['pipeline_run_id'],
            ['pipeline_runs.id'],
            name=op.f('fk_pipeline_run_calls_pipeline_run_id_pipeline_runs'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_pipeline_run_calls')),
        sa.UniqueConstraint(
            'pipeline_run_id',
            'sequence',
            name=op.f('uq_pipeline_run_calls_pipeline_run_id_sequence'),
        ),
    )
    with op.batch_alter_table('pipeline_run_calls', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_pipeline_run_calls_pipeline_run_id'), ['pipeline_run_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_pipeline_run_calls_request_hash'), ['request_hash'], unique=False
        )
    with op.batch_alter_table('pipeline_runs', schema=None, recreate='never') as batch_op:
        batch_op.add_column(sa.Column('resumed_from_run_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # recreate='never': ALTER TABLE ... DROP COLUMN (SQLite >= 3.35), so the
    # cascade never deletes Dataset Versions.
    with op.batch_alter_table('pipeline_runs', schema=None, recreate='never') as batch_op:
        batch_op.drop_column('resumed_from_run_id')
    with op.batch_alter_table('pipeline_run_calls', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_pipeline_run_calls_request_hash'))
        batch_op.drop_index(batch_op.f('ix_pipeline_run_calls_pipeline_run_id'))
    op.drop_table('pipeline_run_calls')
