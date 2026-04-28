"""Collect and sort upcoming events from post.events JSON fields."""
from collections import Counter
from datetime import date, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.post import Post
from app.models.channel import Channel


async def get_upcoming_events(
    db: AsyncSession,
    user_id: int,
    days_ahead: int = 7,
    date_from: date | None = None,
    date_to: date | None = None,
    event_type: str | None = None,
) -> list[dict]:
    """Return events extracted from posts, enriched with channel info and mention counts."""
    stmt = (
        select(Post, Channel.title.label("channel_title"), Channel.username.label("channel_username"))
        .join(Channel, Post.channel_id == Channel.id)
        .where(Channel.user_id == user_id)
        .where(Post.events != None)   # noqa: E711
    )
    rows = (await db.execute(stmt)).all()

    today = date.today()
    cutoff_from = date_from or today
    cutoff_to = date_to or (today + timedelta(days=days_ahead))

    # Collect all matching events with context
    raw: list[dict] = []
    for row in rows:
        post = row.Post
        for ev in (post.events or []):
            ev_date_str = ev.get("date")
            ev_date: date | None = None
            if ev_date_str:
                try:
                    ev_date = date.fromisoformat(ev_date_str)
                except ValueError:
                    pass

            # Date filter
            if ev_date and (ev_date < cutoff_from or ev_date > cutoff_to):
                continue

            # Event type filter
            if event_type and ev.get("type", "").lower() != event_type.lower():
                continue

            raw.append({
                **ev,
                "_post_id": post.id,
                "_channel_title": row.channel_title,
                "_channel_username": row.channel_username,
                "_post_category": post.category,
                "_ev_date_obj": ev_date,
            })

    # Count mentions per event name (case-insensitive)
    name_counts: Counter = Counter(
        e.get("name", "").strip().lower() for e in raw if e.get("name")
    )

    # Deduplicate by name, keep first occurrence, attach mentions count
    seen: set[str] = set()
    result: list[dict] = []
    for ev in raw:
        name_key = ev.get("name", "").strip().lower()
        if name_key and name_key in seen:
            continue
        if name_key:
            seen.add(name_key)

        clean = {k: v for k, v in ev.items() if not k.startswith("_")}
        clean["channel_title"] = ev["_channel_title"]
        clean["channel_username"] = ev["_channel_username"]
        clean["post_category"] = ev["_post_category"]
        clean["mentions"] = name_counts.get(name_key, 1) if name_key else 1
        result.append(clean)

    result.sort(key=lambda e: e.get("date") or "9999-12-31")
    return result
