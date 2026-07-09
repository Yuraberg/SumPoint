"""Aggregate statistics for the analytics dashboard.

All queries are owner-scoped through ``channels.user_id`` so one user's numbers
never leak into another's. ``posts.published_at`` is TIMESTAMP WITHOUT TIME ZONE
(see CLAUDE.md), so day bucketing uses ``func.date()`` on naive timestamps.
"""
from datetime import date, datetime, timedelta

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channel import Channel
from app.models.post import Post


def _owned_posts(user_id: int):
    """Base select of the user's own, non-ad posts joined to their channels."""
    return (
        select(Post)
        .join(Channel, Post.channel_id == Channel.id)
        .where(Channel.user_id == user_id)
        .where(Post.is_ad.is_(False))
    )


async def totals(db: AsyncSession, user_id: int) -> dict:
    """Headline counters: total posts, channels, unread, posts with events."""
    posts_q = (
        select(func.count(Post.id))
        .join(Channel, Post.channel_id == Channel.id)
        .where(Channel.user_id == user_id)
        .where(Post.is_ad.is_(False))
    )
    unread_q = posts_q.where(Post.read_at.is_(None))
    events_q = posts_q.where(Post.events.isnot(None))
    channels_q = select(func.count(Channel.id)).where(Channel.user_id == user_id)

    return {
        "posts": (await db.execute(posts_q)).scalar_one(),
        "unread": (await db.execute(unread_q)).scalar_one(),
        "events": (await db.execute(events_q)).scalar_one(),
        "channels": (await db.execute(channels_q)).scalar_one(),
    }


async def posts_per_day(db: AsyncSession, user_id: int, *, days: int = 30) -> list[dict]:
    """Post counts per calendar day for the last ``days`` days, zero-filled so
    the chart has one bar per day even when nothing was collected."""
    today = date.today()
    since = datetime(today.year, today.month, today.day) - timedelta(days=days - 1)

    day_col = func.date(Post.published_at)
    stmt = (
        select(day_col.label("day"), func.count(Post.id).label("count"))
        .join(Channel, Post.channel_id == Channel.id)
        .where(Channel.user_id == user_id)
        .where(Post.is_ad.is_(False))
        .where(Post.published_at >= since)
        .group_by(day_col)
    )
    rows = (await db.execute(stmt)).all()
    # func.date() returns a date on asyncpg; normalise to isoformat keys.
    counts = {(r.day.isoformat() if hasattr(r.day, "isoformat") else str(r.day)): r.count
              for r in rows}

    out = []
    for i in range(days):
        d = (since + timedelta(days=i)).date().isoformat()
        out.append({"date": d, "count": counts.get(d, 0)})
    return out


async def posts_per_category(db: AsyncSession, user_id: int) -> list[dict]:
    """Non-ad post counts grouped by category, largest first."""
    stmt = (
        select(Post.category, func.count(Post.id).label("count"))
        .join(Channel, Post.channel_id == Channel.id)
        .where(Channel.user_id == user_id)
        .where(Post.is_ad.is_(False))
        .group_by(Post.category)
        .order_by(func.count(Post.id).desc())
    )
    rows = (await db.execute(stmt)).all()
    return [{"category": r.category or "без категории", "count": r.count} for r in rows]


async def posts_per_channel(db: AsyncSession, user_id: int, *, limit: int = 12) -> list[dict]:
    """Top channels by non-ad post count."""
    stmt = (
        select(
            Channel.id,
            Channel.title,
            Channel.username,
            func.count(Post.id).label("count"),
        )
        .join(Post, Post.channel_id == Channel.id)
        .where(Channel.user_id == user_id)
        .where(Post.is_ad.is_(False))
        .group_by(Channel.id, Channel.title, Channel.username)
        .order_by(func.count(Post.id).desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    return [
        {"channel_id": r.id, "title": r.title, "username": r.username, "count": r.count}
        for r in rows
    ]


async def channel_health(db: AsyncSession, user_id: int) -> list[dict]:
    """Per-channel operational health for the Channels page: post count, unread
    count, last fetch time and last error. LEFT JOINs so channels with zero
    posts still appear (a silently-broken channel is exactly what we want to
    surface here)."""
    post_count = func.count(Post.id).label("post_count")
    unread_count = cast(
        func.count(Post.id).filter(Post.read_at.is_(None)), Integer
    ).label("unread_count")

    stmt = (
        select(
            Channel.id,
            Channel.title,
            Channel.username,
            Channel.is_active,
            Channel.last_fetched_at,
            Channel.last_error,
            post_count,
            unread_count,
        )
        .outerjoin(Post, (Post.channel_id == Channel.id) & (Post.is_ad.is_(False)))
        .where(Channel.user_id == user_id)
        .group_by(Channel.id)
        .order_by(Channel.title)
    )
    rows = (await db.execute(stmt)).all()
    return [
        {
            "channel_id": r.id,
            "title": r.title,
            "username": r.username,
            "is_active": r.is_active,
            "last_fetched_at": r.last_fetched_at.isoformat() if r.last_fetched_at else None,
            "last_error": r.last_error,
            "post_count": r.post_count,
            "unread_count": r.unread_count,
        }
        for r in rows
    ]
