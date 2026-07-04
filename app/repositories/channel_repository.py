"""Channel queries."""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channel import Channel
from app.models.user import User


async def get_for_user(db: AsyncSession, user_id: int) -> list[Channel]:
    return (
        await db.execute(select(Channel).where(Channel.user_id == user_id))
    ).scalars().all()


async def get_for_user_ordered(db: AsyncSession, user_id: int) -> list[Channel]:
    return (
        await db.execute(
            select(Channel).where(Channel.user_id == user_id).order_by(Channel.title)
        )
    ).scalars().all()


async def get_owned(db: AsyncSession, channel_id: int, user_id: int) -> Channel | None:
    return (
        await db.execute(
            select(Channel).where(Channel.id == channel_id, Channel.user_id == user_id)
        )
    ).scalar_one_or_none()


async def get_by_telegram_id(
    db: AsyncSession, user_id: int, telegram_id: int
) -> Channel | None:
    return (
        await db.execute(
            select(Channel).where(
                Channel.user_id == user_id,
                Channel.telegram_id == telegram_id,
            )
        )
    ).scalar_one_or_none()


async def get_fetch_batch(
    db: AsyncSession, batch_size: int, *, require_session_path: bool
) -> list[tuple[Channel, User]]:
    """Active channels joined with their owner, oldest ``last_fetched_at`` first.

    Bounded to ``batch_size`` so each fetch tick processes a small slice of
    channels — spreads Telethon traffic across runs instead of bursting.
    ``require_session_path`` skips users without a session file when no global
    ``TELEGRAM_SESSION_STRING`` is configured.
    """
    stmt = (
        select(Channel, User)
        .join(User, Channel.user_id == User.id)
        .where(Channel.is_active.is_(True), User.is_active.is_(True))
    )
    if require_session_path:
        stmt = stmt.where(User.session_path.isnot(None))
    stmt = stmt.order_by(Channel.last_fetched_at.asc().nulls_first()).limit(batch_size)
    return (await db.execute(stmt)).all()


def mark_fetched(channel: Channel, when: datetime, *, error: str | None = None) -> None:
    """Update fetch bookkeeping on a channel (caller commits)."""
    channel.last_fetched_at = when
    channel.last_error = error[:1000] if error else None
