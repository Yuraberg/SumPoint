"""add favorites table

Revision ID: 7245fa6d1b69
Revises: b8f3e6d1a4c7
Create Date: 2026-07-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7245fa6d1b69'
down_revision: Union[str, None] = 'b8f3e6d1a4c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'favorites',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('post_id', sa.BigInteger(), nullable=False),
        sa.Column('event_index', sa.Integer(), nullable=False, server_default='-1'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['post_id'], ['posts.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('user_id', 'post_id', 'event_index', name='uq_favorites_user_post_event'),
    )
    op.create_index('ix_favorites_user_id', 'favorites', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_favorites_user_id', table_name='favorites')
    op.drop_table('favorites')
