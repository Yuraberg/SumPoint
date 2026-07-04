"""Build daily digest from stored posts."""
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import DEFAULT_DIGEST_HOURS
from app.repositories import post_repository
from app.services.ai_engine import generate_digest_text
from app.utils.time import utcnow


async def build_user_digest(
    db: AsyncSession,
    user_id: int,
    hours: int = DEFAULT_DIGEST_HOURS,
    categories: list[str] | None = None,
    model: str | None = None,
) -> dict:
    """Collect recent posts for a user and produce a markdown digest.

    categories — if provided, only include posts whose category is in this list.
    model      — DeepSeek model name; None defaults to the configured model.
    """
    cutoff = utcnow() - timedelta(hours=hours)
    rows = await post_repository.get_digest_feed(
        db, user_id, since=cutoff, categories=categories
    )

    if not rows:
        return {
            "generated_at": utcnow(),
            "user_id": user_id,
            "posts": [],
            "events": [],
            "digest_markdown": None,
        }

    summaries = [
        {
            "channel": row.channel_title,
            "summary": row.Post.summary or "",
            "category": row.Post.category or "Прочее",
        }
        for row in rows
    ]

    digest_text = await generate_digest_text(summaries, model=model)

    all_events: list = []
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
        "generated_at": utcnow(),
        "user_id": user_id,
        "digest_markdown": digest_text,
        "posts": posts_out,
        "events": all_events,
    }
