"""add token_version to users for JWT revocation

Revision ID: a7d4e1c9b2f8
Revises: f6c3d9a2e4b7
Create Date: 2026-07-09 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7d4e1c9b2f8'
down_revision: Union[str, None] = 'f6c3d9a2e4b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('token_version', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('users', 'token_version')
