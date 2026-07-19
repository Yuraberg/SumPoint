"""Favorite (bookmark) queries for posts and calendar events.

Posts are favorited as themselves (``event_index = WHOLE_POST``); calendar
events don't have their own row (they're a JSON list embedded in
``Post.events``), so an event favorite is keyed by ``(post_id, event_index)``
— stable as long as ``events`` isn't rewritten after ingestion, which it
currently never is (see ``process_post``).
"""
from sqlalchemy import Row, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channel import Channel
from app.models.favorite import WHOLE_POST, Favorite
from app.models.post import Post


async def _get_owned_post(db: AsyncSession, user_id: int, post_id: int) -> Post | None:
    """The post if it belongs to one of the user's channels, else None."""
    stmt = (
        select(Post)
        .join(Channel, Post.channel_id == Channel.id)
        .where(Channel.user_id == user_id, Post.id == post_id)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def toggle(
    db: AsyncSession, user_id: int, post_id: int, event_index: int = WHOLE_POST
) -> bool:
    """Add or remove a favorite. Returns the new state (True = now favorited).

    Raises ``LookupError`` if the post isn't owned by the user, or
    ``event_index`` doesn't point at a real entry in that post's events.
    """
    post = await _get_owned_post(db, user_id, post_id)
    if post is None:
        raise LookupError("post not found")
    if event_index != WHOLE_POST:
        events = post.events or []
        if not (0 <= event_index < len(events)):
            raise LookupError("event index out of range")

    existing = (
        await db.execute(
            select(Favorite).where(
                Favorite.user_id == user_id,
                Favorite.post_id == post_id,
                Favorite.event_index == event_index,
            )
        )
    ).scalar_one_or_none()

    if existing:
        await db.delete(existing)
        await db.commit()
        return False

    db.add(Favorite(user_id=user_id, post_id=post_id, event_index=event_index))
    await db.commit()
    return True


async def list_favorite_posts(
    db: AsyncSession, user_id: int, *, category: str | None = None
) -> list[Row]:
    """Rows of (Post, channel_username, channel_title, favorited_at), newest
    favorite first."""
    stmt = (
        select(
            Post,
            Channel.username.label("channel_username"),
            Channel.title.label("channel_title"),
            Favorite.created_at.label("favorited_at"),
        )
        .join(
            Favorite,
            and_(
                Favorite.post_id == Post.id,
                Favorite.user_id == user_id,
                Favorite.event_index == WHOLE_POST,
            ),
        )
        .join(Channel, Post.channel_id == Channel.id)
    )
    if category:
        stmt = stmt.where(Post.category == category)
    stmt = stmt.order_by(Favorite.created_at.desc())
    return (await db.execute(stmt)).all()


async def list_favorite_events(db: AsyncSession, user_id: int) -> list[Row]:
    """Rows of (Post, event_index, channel_username, channel_title,
    favorited_at) for favorited events, newest favorite first. Caller pulls
    the actual event dict out of ``Post.events[event_index]``."""
    stmt = (
        select(
            Post,
            Favorite.event_index,
            Channel.username.label("channel_username"),
            Channel.title.label("channel_title"),
            Favorite.created_at.label("favorited_at"),
        )
        .join(
            Favorite,
            and_(Favorite.post_id == Post.id, Favorite.user_id == user_id),
        )
        .join(Channel, Post.channel_id == Channel.id)
        .where(Favorite.event_index != WHOLE_POST)
        .order_by(Favorite.created_at.desc())
    )
    return (await db.execute(stmt)).all()


async def get_favorite_post_ids(
    db: AsyncSession, user_id: int, post_ids: list[int]
) -> set[int]:
    """Bulk membership check — which of ``post_ids`` the user has favorited
    as a whole post. Used to annotate feed/search results."""
    if not post_ids:
        return set()
    stmt = select(Favorite.post_id).where(
        Favorite.user_id == user_id,
        Favorite.event_index == WHOLE_POST,
        Favorite.post_id.in_(post_ids),
    )
    return set((await db.execute(stmt)).scalars().all())


async def get_favorite_event_keys(db: AsyncSession, user_id: int) -> set[tuple[int, int]]:
    """All (post_id, event_index) pairs the user has favorited. Used to
    annotate the upcoming-events list."""
    stmt = select(Favorite.post_id, Favorite.event_index).where(
        Favorite.user_id == user_id, Favorite.event_index != WHOLE_POST
    )
    return {(row.post_id, row.event_index) for row in (await db.execute(stmt))}
