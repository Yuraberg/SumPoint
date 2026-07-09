"""add content_hash to posts and last_error to channels

Revision ID: f94baacc62fc
Revises: 6676f8b9885c
Create Date: 2026-06-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f94baacc62fc'
down_revision: Union[str, None] = '6676f8b9885c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('posts', sa.Column('content_hash', sa.String(length=64), nullable=True))
    # CONCURRENTLY avoids a write-blocking lock on posts while the index
    # builds — matters once the table has real row counts. It can't run
    # inside a transaction, hence the autocommit block.
    with op.get_context().autocommit_block():
        op.execute(
            'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_posts_content_hash '
            'ON posts (content_hash)'
        )
    op.add_column('channels', sa.Column('last_error', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('channels', 'last_error')
    with op.get_context().autocommit_block():
        op.execute('DROP INDEX CONCURRENTLY IF EXISTS ix_posts_content_hash')
    op.drop_column('posts', 'content_hash')
