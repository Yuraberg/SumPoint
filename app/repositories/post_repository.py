"""Post queries: listing, keyword search, semantic search, dedup, digest feed."""
from datetime import date, datetime, timedelta

from sqlalchemy import Row, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channel import Channel
from app.models.post import Post
from app.utils.time import utcnow


def escape_like(value: str) -> str:
    """Escape ILIKE wildcard characters so user input is matched literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_for_user(
    db: AsyncSession,
    user_id: int,
    *,
    category: str | None = None,
    channel_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    unread_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[Row]:
    """Rows of (Post, channel_username, channel_title) for the feed view."""
    stmt = (
        select(
            Post,
            Channel.username.label("channel_username"),
            Channel.title.label("channel_title"),
        )
        .join(Channel, Post.channel_id == Channel.id)
        .where(Channel.user_id == user_id)
        .where(Post.is_ad.is_(False))
    )
    if category:
        stmt = stmt.where(Post.category == category)
    if channel_id:
        stmt = stmt.where(Post.channel_id == channel_id)
    if unread_only:
        stmt = stmt.where(Post.read_at.is_(None))
    if date_from:
        stmt = stmt.where(
            Post.published_at >= datetime(date_from.year, date_from.month, date_from.day)
        )
    if date_to:
        # Half-open upper bound; timedelta avoids the day+1 month-boundary crash.
        stmt = stmt.where(
            Post.published_at
            < datetime(date_to.year, date_to.month, date_to.day) + timedelta(days=1)
        )
    stmt = stmt.order_by(Post.published_at.desc()).offset(offset).limit(limit)
    return (await db.execute(stmt)).all()


# The unread subquery / update statements below all re-scope to the caller's
# own posts (posts → channels.user_id) so one user can never read or mutate
# another user's read state by guessing post ids.
def _user_post_ids(user_id: int):
    return (
        select(Post.id)
        .join(Channel, Post.channel_id == Channel.id)
        .where(Channel.user_id == user_id)
    )


async def count_unread(db: AsyncSession, user_id: int) -> int:
    """Number of unread, non-ad posts across all of the user's channels."""
    stmt = (
        select(func.count(Post.id))
        .join(Channel, Post.channel_id == Channel.id)
        .where(Channel.user_id == user_id)
        .where(Post.is_ad.is_(False))
        .where(Post.read_at.is_(None))
    )
    return (await db.execute(stmt)).scalar_one()


async def mark_read(db: AsyncSession, user_id: int, post_ids: list[int]) -> int:
    """Mark the given posts read (idempotent). Returns rows affected. Only
    touches posts the user owns; ids they don't own are silently ignored."""
    if not post_ids:
        return 0
    owned = _user_post_ids(user_id).where(Post.id.in_(post_ids)).subquery()
    stmt = (
        update(Post)
        .where(Post.id.in_(select(owned.c.id)))
        .where(Post.read_at.is_(None))
        .values(read_at=utcnow())
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount or 0


async def mark_all_read(
    db: AsyncSession, user_id: int, *, category: str | None = None,
    channel_id: int | None = None,
) -> int:
    """Mark every currently-unread post read, optionally scoped to the same
    category/channel filter the feed is showing. Returns rows affected."""
    owned = _user_post_ids(user_id)
    if category:
        owned = owned.where(Post.category == category)
    if channel_id:
        owned = owned.where(Post.channel_id == channel_id)
    owned_sq = owned.subquery()
    stmt = (
        update(Post)
        .where(Post.id.in_(select(owned_sq.c.id)))
        .where(Post.read_at.is_(None))
        .values(read_at=utcnow())
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount or 0


async def keyword_search(
    db: AsyncSession,
    user_id: int,
    query: str,
    *,
    limit: int = 20,
    offset: int = 0,
    category: str | None = None,
    include_summary: bool = False,
) -> list[Row]:
    """ILIKE search over post text (and optionally summary)."""
    pattern = f"%{escape_like(query)}%"
    match = (
        or_(Post.text.ilike(pattern), Post.summary.ilike(pattern))
        if include_summary
        else Post.text.ilike(pattern)
    )
    stmt = (
        select(
            Post,
            Channel.username.label("channel_username"),
            Channel.title.label("channel_title"),
        )
        .join(Channel, Post.channel_id == Channel.id)
        .where(Channel.user_id == user_id)
        .where(Post.is_ad.is_(False))
        .where(match)
    )
    if category:
        stmt = stmt.where(Post.category == category)
    stmt = stmt.order_by(Post.published_at.desc()).offset(offset).limit(limit)
    return (await db.execute(stmt)).all()


async def semantic_search(
    db: AsyncSession, user_id: int, embedding: list[float], *, limit: int = 20
) -> list[Row]:
    """pgvector cosine-distance search over BGE-M3 embeddings.

    Shared by the REST endpoint and the bot so the raw SQL lives in one place.
    Returns rows with a ``similarity`` column (cosine distance; lower is closer).
    """
    vec_literal = "[" + ",".join(str(x) for x in embedding) + "]"
    sql = text(
        """
        SELECT p.id, p.channel_id, p.telegram_message_id, p.text,
               p.published_at, p.summary, p.category, p.is_ad, p.events,
               p.read_at,
               c.username AS channel_username, c.title AS channel_title,
               p.embedding <=> CAST(:query_vec AS vector) AS similarity
        FROM posts p
        JOIN channels c ON c.id = p.channel_id
        WHERE c.user_id = :user_id
          AND p.is_ad = false
          AND p.embedding IS NOT NULL
        ORDER BY similarity
        LIMIT :lim
        """
    )
    return (
        await db.execute(
            sql, {"query_vec": vec_literal, "user_id": user_id, "lim": limit}
        )
    ).all()


async def exists_by_message_id(
    db: AsyncSession, channel_id: int, telegram_message_id: int
) -> bool:
    row = (
        await db.execute(
            select(Post.id).where(
                Post.channel_id == channel_id,
                Post.telegram_message_id == telegram_message_id,
            )
        )
    ).scalar_one_or_none()
    return row is not None


async def exists_by_content_hash(
    db: AsyncSession, channel_id: int, content_hash: str, since: datetime
) -> bool:
    """Whether an identical-text repost exists within the dedup window."""
    row = (
        await db.execute(
            select(Post.id).where(
                Post.channel_id == channel_id,
                Post.content_hash == content_hash,
                Post.published_at >= since,
            )
        )
    ).scalar_one_or_none()
    return row is not None


async def get_digest_feed(
    db: AsyncSession, user_id: int, *, since: datetime, categories: list[str] | None = None
) -> list[Row]:
    """Rows of (Post, channel_title) for building a digest, newest first."""
    stmt = (
        select(Post, Channel.title.label("channel_title"))
        .join(Channel, Post.channel_id == Channel.id)
        .where(Channel.user_id == user_id)
        .where(Post.published_at >= since)
        .where(Post.is_ad.is_(False))
        .where(Post.summary.isnot(None))
        .order_by(Post.published_at.desc())
    )
    if categories:
        stmt = stmt.where(Post.category.in_(categories))
    return (await db.execute(stmt)).all()


async def get_events_feed(db: AsyncSession, user_id: int) -> list[Row]:
    """Rows of (post_id, events, category, channel_title, channel_username) for
    posts that carry extracted calendar events. Selects only the needed columns
    so the 1024-float embedding vectors are never loaded."""
    stmt = (
        select(
            Post.id,
            Post.events,
            Post.category,
            Channel.title.label("channel_title"),
            Channel.username.label("channel_username"),
        )
        .join(Channel, Post.channel_id == Channel.id)
        .where(Channel.user_id == user_id)
        .where(Post.events.isnot(None))
    )
    return (await db.execute(stmt)).all()


async def get_recent_for_category(
    db: AsyncSession, user_id: int, category: str | None, *, limit: int = 5
) -> list[Row]:
    """Latest (Post, channel_title) rows, optionally filtered by category."""
    stmt = (
        select(
            Post.text,
            Post.summary,
            Post.published_at,
            Post.category,
            Channel.title.label("channel_title"),
        )
        .join(Channel, Post.channel_id == Channel.id)
        .where(Channel.user_id == user_id)
        .where(Post.is_ad.is_(False))
    )
    if category:
        stmt = stmt.where(Post.category == category)
    stmt = stmt.order_by(Post.published_at.desc()).limit(limit)
    return (await db.execute(stmt)).all()
