"""add keyword_alerts table

Revision ID: a1c5e9f2b3d4
Revises: f94baacc62fc
Create Date: 2026-06-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1c5e9f2b3d4'
down_revision: Union[str, None] = 'f94baacc62fc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'keyword_alerts',
        sa.Column('id', sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('keyword', sa.String(length=128), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('user_id', 'keyword', name='uq_keyword_alerts_user_keyword'),
    )


def downgrade() -> None:
    op.drop_table('keyword_alerts')
