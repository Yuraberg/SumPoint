"""Build daily digest from stored posts."""
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.post import Post
from app.models.channel import Channel
from app.prompts.summarization import build_digest_prompt
from app.services.ai_engine import _call


async def build_user_digest(db: AsyncSession, user_id: int, hours: int = 24) -> dict:
    """Collect recent posts for a user and produce a markdown digest."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours)

    stmt = (
        select(Post, Channel.title.label("channel_title"))
        .join(Channel, Post.channel_id == Channel.id)
        .where(Channel.user_id == user_id)
        .where(Post.published_at >= cutoff)
        .where(Post.is_ad == False)          # noqa: E712
        .where(Post.summary != None)         # noqa: E711
        .order_by(Post.published_at.desc())
    )
    rows = (await db.execute(stmt)).all()

    if not rows:
        return {"generated_at": datetime.utcnow(), "user_id": user_id, "posts": [], "events": []}

    summaries = [
        {"channel": row.channel_title, "summary": row.Post.summary or "", "category": row.Post.category or "Other"}
        for row in rows
    ]

    digest_text = _call(build_digest_prompt(summaries), max_tokens=1024)

    # Collect all events
    all_events = []
    for row in rows:
        if row.Post.events:
            all_events.extend(row.Post.events)

    posts_out = [
        {
            "id": row.Post.id,
            "channel_id": row.Post.channel_id,
            "telegram_message_id": row.Post.telegram_message_id,
            "text": row.Post.text,
            "published_at": row.Post.published_at,
            "summary": row.Post.summary,
            "category": row.Post.category,
            "is_ad": row.Post.is_ad,
            "events": row.Post.events,
        }
        for row in rows
    ]

    return {
        "generated_at": datetime.utcnow(),
        "user_id": user_id,
        "digest_markdown": digest_text,
        "posts": posts_out,
        "events": all_events,
    }
