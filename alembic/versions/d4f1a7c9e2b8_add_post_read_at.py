"""add read_at to posts for unread tracking

Revision ID: d4f1a7c9e2b8
Revises: c3e8a1f4d9b7
Create Date: 2026-07-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4f1a7c9e2b8'
down_revision: Union[str, None] = 'c3e8a1f4d9b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable timestamp: NULL means unread, a value is the moment it was read.
    # A partial index on the unread rows keeps the sidebar "unread count" query
    # and the unread-only feed filter fast without indexing the (growing) bulk
    # of already-read posts.
    op.add_column('posts', sa.Column('read_at', sa.DateTime(), nullable=True))
    with op.get_context().autocommit_block():
        op.execute(
            'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_posts_unread '
            'ON posts (channel_id) WHERE read_at IS NULL'
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute('DROP INDEX CONCURRENTLY IF EXISTS ix_posts_unread')
    op.drop_column('posts', 'read_at')
