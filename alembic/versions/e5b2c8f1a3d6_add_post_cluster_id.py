"""add cluster_id to posts for duplicate grouping

Revision ID: e5b2c8f1a3d6
Revises: d4f1a7c9e2b8
Create Date: 2026-07-09 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5b2c8f1a3d6'
down_revision: Union[str, None] = 'd4f1a7c9e2b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable: a post points at the id of its cluster's representative post;
    # NULL means "not clustered" (embedding was unavailable). Index makes the
    # per-cluster distinct-channel count (feed badge) and the cluster-members
    # lookup fast. Built CONCURRENTLY so it doesn't lock the posts table.
    op.add_column('posts', sa.Column('cluster_id', sa.BigInteger(), nullable=True))
    with op.get_context().autocommit_block():
        op.execute(
            'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_posts_cluster_id '
            'ON posts (cluster_id)'
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute('DROP INDEX CONCURRENTLY IF EXISTS ix_posts_cluster_id')
    op.drop_column('posts', 'cluster_id')
