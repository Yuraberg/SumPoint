"""Post retrieval and semantic search endpoints."""
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.database import get_db
from app.models.post import Post
from app.repositories import post_repository
from app.repositories.post_repository import (
    escape_like as _escape_like,  # noqa: F401  (re-exported)
)
from app.schemas.post import PostOut
from app.services.ai_engine import generate_embedding

router = APIRouter(prefix="/posts", tags=["posts"])


def _to_post_out(post: Post, channel_username: str | None, channel_title: str | None,
                 similarity: float | None = None) -> PostOut:
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
        similarity=similarity,
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
    rows = await post_repository.list_for_user(
        db, current_user.id,
        category=category, channel_id=channel_id,
        date_from=date_from, date_to=date_to,
        limit=limit, offset=offset,
    )
    return [_to_post_out(row.Post, row.channel_username, row.channel_title) for row in rows]


@router.get("/search", response_model=list[PostOut])
async def search_posts(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    q: str = Query(..., min_length=2),
    limit: int = Query(20, le=100),
):
    rows = await post_repository.keyword_search(db, current_user.id, q, limit=limit)
    return [_to_post_out(row.Post, row.channel_username, row.channel_title) for row in rows]


@router.get("/semantic-search", response_model=list[PostOut])
async def semantic_search_posts(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    q: str = Query(..., min_length=2),
    limit: int = Query(20, le=100),
):
    """Semantic search: embed query with BGE-M3 via Ollama, then pgvector cosine search."""
    embedding = await generate_embedding(q)
    rows = await post_repository.semantic_search(db, current_user.id, embedding, limit=limit)

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
        results.append(
            _to_post_out(
                post, row.channel_username, row.channel_title,
                similarity=round(float(row.similarity), 4),
            )
        )
    return results
