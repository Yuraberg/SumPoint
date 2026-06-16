"""Post retrieval and semantic search endpoints."""
from datetime import date, datetime
from typing import Annotated
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from app.database import get_db
from app.models.post import Post
from app.models.channel import Channel
from app.models.user import User
from app.schemas.post import PostOut
from app.api.auth import get_current_user
from app.services.ai_engine import generate_embedding

router = APIRouter(prefix="/posts", tags=["posts"])
CurrentUser = Annotated[User, Depends(get_current_user)]


def _to_post_out(post: Post, channel_username: str | None, channel_title: str | None) -> PostOut:
    return PostOut(
        id=post.id,
        channel_id=post.channel_id,
        telegram_message_id=post.telegram_message_id,
        text=post.text,
        published_at=post.published_at,
        summary=post.summary,
        category=post.category,
        is_ad=post.is_ad,
        events=post.events,
        channel_username=channel_username,
        channel_title=channel_title,
    )


@router.get("/", response_model=list[PostOut])
async def list_posts(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    category: str | None = Query(None),
    channel_id: int | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    stmt = (
        select(Post, Channel.username.label("channel_username"), Channel.title.label("channel_title"))
        .join(Channel, Post.channel_id == Channel.id)
        .where(Channel.user_id == current_user.id)
        .where(Post.is_ad == False)   # noqa: E712
    )
    if category:
        stmt = stmt.where(Post.category == category)
    if channel_id:
        stmt = stmt.where(Post.channel_id == channel_id)
    if date_from:
        stmt = stmt.where(Post.published_at >= datetime(date_from.year, date_from.month, date_from.day))
    if date_to:
        stmt = stmt.where(Post.published_at < datetime(date_to.year, date_to.month, date_to.day + 1))
    stmt = stmt.order_by(Post.published_at.desc()).offset(offset).limit(limit)
    rows = (await db.execute(stmt)).all()
    return [_to_post_out(row.Post, row.channel_username, row.channel_title) for row in rows]


@router.get("/search", response_model=list[PostOut])
async def search_posts(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    q: str = Query(..., min_length=2),
    limit: int = Query(20, le=100),
):
    stmt = (
        select(Post, Channel.username.label("channel_username"), Channel.title.label("channel_title"))
        .join(Channel, Post.channel_id == Channel.id)
        .where(Channel.user_id == current_user.id)
        .where(Post.is_ad == False)   # noqa: E712
        .where(Post.text.ilike(f"%{q}%"))
        .order_by(Post.published_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    return [_to_post_out(row.Post, row.channel_username, row.channel_title) for row in rows]


@router.get("/semantic-search", response_model=list[PostOut])
async def semantic_search_posts(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    q: str = Query(..., min_length=2),
    limit: int = Query(20, le=100),
):
    """Semantic search: embed query with BGE-M3 via Ollama, then pgvector cosine search."""
    embedding = generate_embedding(q)
    vec_literal = "[" + ",".join(str(x) for x in embedding) + "]"

    sql = text("""
        SELECT p.id, p.channel_id, p.telegram_message_id, p.text,
               p.published_at, p.summary, p.category, p.is_ad, p.events,
               c.username AS channel_username, c.title AS channel_title,
               p.embedding <=> CAST(:query_vec AS vector) AS similarity
        FROM posts p
        JOIN channels c ON c.id = p.channel_id
        WHERE c.user_id = :user_id
          AND p.is_ad = false
          AND p.embedding IS NOT NULL
        ORDER BY similarity
        LIMIT :lim
    """)
    rows = (await db.execute(sql, {"query_vec": vec_literal, "user_id": current_user.id, "lim": limit})).all()

    results = []
    for row in rows:
        post = Post(
            id=row.id,
            channel_id=row.channel_id,
            telegram_message_id=row.telegram_message_id,
            text=row.text,
            published_at=row.published_at,
            summary=row.summary,
            category=row.category,
            is_ad=row.is_ad,
            events=row.events,
        )
        out = _to_post_out(post, row.channel_username, row.channel_title)
        out.similarity = round(float(row.similarity), 4)
        results.append(out)
    return results
