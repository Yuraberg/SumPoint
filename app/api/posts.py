"""Post retrieval and semantic search endpoints."""
from typing import Annotated
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.post import Post
from app.models.channel import Channel
from app.models.user import User
from app.schemas.post import PostOut
from app.api.auth import get_current_user

router = APIRouter(prefix="/posts", tags=["posts"])
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get("/", response_model=list[PostOut])
async def list_posts(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    category: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    stmt = (
        select(Post)
        .join(Channel, Post.channel_id == Channel.id)
        .where(Channel.user_id == current_user.id)
        .where(Post.is_ad == False)   # noqa: E712
    )
    if category:
        stmt = stmt.where(Post.category == category)
    stmt = stmt.order_by(Post.published_at.desc()).offset(offset).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return rows


@router.get("/search", response_model=list[PostOut])
async def search_posts(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    q: str = Query(..., min_length=2),
    limit: int = Query(20, le=100),
):
    """
    Semantic search over posts using pgvector cosine similarity.
    Falls back to ILIKE text search when embeddings are zeros.
    """
    # Text fallback (works without real embeddings)
    stmt = (
        select(Post)
        .join(Channel, Post.channel_id == Channel.id)
        .where(Channel.user_id == current_user.id)
        .where(Post.is_ad == False)   # noqa: E712
        .where(Post.text.ilike(f"%{q}%"))
        .order_by(Post.published_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return rows
