"""schedules: allow 'disabled' status; magic_links: cascade on user delete

Revision ID: c3e8a1f4d9b7
Revises: b2d7f3a1c8e5
Create Date: 2026-07-04 00:00:00.000000

The schedule runner disables a schedule with an unparseable cron_expr by setting
status='disabled'; the original CHECK only allowed ('active','paused'), so that
write would have raised. This widens the CHECK. It also adds ON DELETE CASCADE
to magic_links.user_id so login links don't outlive a deleted user.
"""
from typing import Sequence, Union
from alembic import op


revision: str = "c3e8a1f4d9b7"
down_revision: Union[str, None] = "b2d7f3a1c8e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── schedules.status CHECK: add 'disabled' ────────────────────────────────
    op.drop_constraint("ck_schedules_status", "schedules", type_="check")
    op.create_check_constraint(
        "ck_schedules_status",
        "schedules",
        "status IN ('active', 'paused', 'disabled')",
    )

    # ── magic_links.user_id FK: ON DELETE CASCADE ─────────────────────────────
    op.drop_constraint("magic_links_user_id_fkey", "magic_links", type_="foreignkey")
    op.create_foreign_key(
        "magic_links_user_id_fkey",
        "magic_links",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("magic_links_user_id_fkey", "magic_links", type_="foreignkey")
    op.create_foreign_key(
        "magic_links_user_id_fkey",
        "magic_links",
        "users",
        ["user_id"],
        ["id"],
    )

    # Revert any 'disabled' rows to 'paused' before tightening the CHECK again.
    op.execute("UPDATE schedules SET status = 'paused' WHERE status = 'disabled'")
    op.drop_constraint("ck_schedules_status", "schedules", type_="check")
    op.create_check_constraint(
        "ck_schedules_status",
        "schedules",
        "status IN ('active', 'paused')",
    )
