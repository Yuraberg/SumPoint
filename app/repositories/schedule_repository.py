"""Schedule (v2 cron) and DigestSchedule queries."""
from datetime import datetime

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schedule import Schedule
from app.models.digest_schedule import DigestSchedule


# ── Schedule v2 (cron) ────────────────────────────────────────────────────────

async def get_owned(db: AsyncSession, sched_id: int, user_id: int) -> Schedule | None:
    return (
        await db.execute(
            select(Schedule).where(Schedule.id == sched_id, Schedule.user_id == user_id)
        )
    ).scalar_one_or_none()


async def list_for_user(db: AsyncSession, user_id: int) -> list[Schedule]:
    return (
        await db.execute(
            select(Schedule)
            .where(Schedule.user_id == user_id)
            .order_by(Schedule.created_at.desc())
        )
    ).scalars().all()


async def claim_due(db: AsyncSession, now: datetime) -> list[Schedule]:
    """Active schedules whose next run is due, locked FOR UPDATE SKIP LOCKED.

    Concurrent workers each claim a disjoint subset of due rows, so a schedule
    is never fired twice in the same minute.
    """
    result = await db.execute(
        select(Schedule)
        .where(
            Schedule.status == "active",
            or_(Schedule.next_run_at <= now, Schedule.next_run_at.is_(None)),
        )
        .with_for_update(skip_locked=True)
    )
    return result.scalars().all()


# ── DigestSchedule (fixed morning/evening slots) ──────────────────────────────

async def get_digest_slot(
    db: AsyncSession, user_id: int, slot: str, *, enabled_only: bool = False
) -> DigestSchedule | None:
    stmt = select(DigestSchedule).where(
        DigestSchedule.user_id == user_id,
        DigestSchedule.slot == slot,
    )
    if enabled_only:
        stmt = stmt.where(DigestSchedule.enabled.is_(True))
    return (await db.execute(stmt)).scalar_one_or_none()
