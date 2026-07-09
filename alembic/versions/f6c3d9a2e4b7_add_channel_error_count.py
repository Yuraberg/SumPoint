"""add error_count to channels for auto-deactivation

Revision ID: f6c3d9a2e4b7
Revises: e5b2c8f1a3d6
Create Date: 2026-07-09 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f6c3d9a2e4b7'
down_revision: Union[str, None] = 'e5b2c8f1a3d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default='0' backfills existing rows without a table rewrite lock;
    # the ORM default handles new inserts.
    op.add_column(
        'channels',
        sa.Column('error_count', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('channels', 'error_count')
