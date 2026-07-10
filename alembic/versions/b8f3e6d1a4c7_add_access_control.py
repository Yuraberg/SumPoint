"""add is_approved to users + invite_codes table for access control

Revision ID: b8f3e6d1a4c7
Revises: a7d4e1c9b2f8
Create Date: 2026-07-10 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8f3e6d1a4c7'
down_revision: Union[str, None] = 'a7d4e1c9b2f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable first so the backfill can distinguish pre-existing rows, then
    # locked to NOT NULL DEFAULT false for everyone signing up from now on.
    # Existing users predate this feature entirely — backfilling them to True
    # means shipping this never locks out someone already using the app.
    op.add_column('users', sa.Column('is_approved', sa.Boolean(), nullable=True))
    op.execute('UPDATE users SET is_approved = true')
    op.alter_column('users', 'is_approved', nullable=False, server_default=sa.false())

    op.create_table(
        'invite_codes',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('code', sa.String(length=16), nullable=False),
        sa.Column('created_by', sa.BigInteger(), nullable=True),
        sa.Column('max_uses', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('uses', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('note', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_invite_codes_code', 'invite_codes', ['code'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_invite_codes_code', table_name='invite_codes')
    op.drop_table('invite_codes')
    op.drop_column('users', 'is_approved')
