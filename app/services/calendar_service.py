"""Collect and sort upcoming events from post.events JSON fields."""
from datetime import date, datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.post import Post
from app.models.channel import Channel


async def get_upcoming_events(db: AsyncSession, user_id: int, days_ahead: int = 7) -> list[dict]:
    """Return events extracted from posts, sorted by date."""
    stmt = (
        select(Post)
        .join(Channel, Post.channel_id == Channel.id)
        .where(Channel.user_id == user_id)
        .where(Post.events != None)   # noqa: E711
    )
    rows = (await db.execute(stmt)).scalars().all()

    today = date.today()
    upcoming = []
    for post in rows:
        for ev in (post.events or []):
            ev_date_str = ev.get("date")
            if not ev_date_str:
                upcoming.append(ev)
                continue
            try:
                ev_date = date.fromisoformat(ev_date_str)
                if 0 <= (ev_date - today).days <= days_ahead:
                    upcoming.append(ev)
            except ValueError:
                upcoming.append(ev)

    # Sort by date, nulls last
    upcoming.sort(key=lambda e: e.get("date") or "9999-12-31")
    return upcoming
