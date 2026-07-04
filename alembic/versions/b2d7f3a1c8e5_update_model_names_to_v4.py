"""update model names to deepseek v4

Revision ID: b2d7f3a1c8e5
Revises: a1c5e9f2b3d4
Create Date: 2026-07-04 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op


revision: str = 'b2d7f3a1c8e5'
down_revision: Union[str, None] = 'a1c5e9f2b3d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE digest_schedules SET model = 'deepseek-v4-flash' WHERE model = 'deepseek-chat'")
    op.execute("UPDATE digest_schedules SET model = 'deepseek-v4-pro' WHERE model = 'deepseek-reasoner'")
    op.execute("UPDATE schedules SET model = 'deepseek-v4-flash' WHERE model = 'deepseek-chat'")
    op.execute("UPDATE schedules SET model = 'deepseek-v4-pro' WHERE model = 'deepseek-reasoner'")


def downgrade() -> None:
    op.execute("UPDATE digest_schedules SET model = 'deepseek-chat' WHERE model = 'deepseek-v4-flash'")
    op.execute("UPDATE digest_schedules SET model = 'deepseek-reasoner' WHERE model = 'deepseek-v4-pro'")
    op.execute("UPDATE schedules SET model = 'deepseek-chat' WHERE model = 'deepseek-v4-flash'")
    op.execute("UPDATE schedules SET model = 'deepseek-reasoner' WHERE model = 'deepseek-v4-pro'")
