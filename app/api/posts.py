"""Post retrieval and semantic search endpoints."""
import csv
import io
import json
from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.database import get_db
from app.models.post import Post
from app.rate_limit import limiter
from app.repositories import favorite_repository, post_repository
from app.repositories.post_repository import (
    escape_like as _escape_like,  # noqa: F401  (re-exported)
)
from app.schemas.post import ClusterMember, PostOut
from app.services.ai_engine import generate_embedding

router = APIRouter(prefix="/posts", tags=["posts"])


class MarkReadIn(BaseModel):
    post_ids: list[int]


def _to_post_out(post: Post, channel_username: str | None, channel_title: str | None,
                 similarity: float | None = None, cluster_size: int | None = None,
                 favorite_post_ids: set[int] | None = None) -> PostOut:
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
        is_read=getattr(post, "read_at", None) is not None,
        is_favorite=post.id in favorite_post_ids if favorite_post_ids else False,
        cluster_id=getattr(post, "cluster_id", None),
        cluster_size=max(cluster_size or 1, 1),
    )


@router.get("/", response_model=list[PostOut])
async def list_posts(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    category: str | None = Query(None),
    channel_id: int | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    unread_only: bool = Query(False),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    rows = await post_repository.list_for_user(
        db, current_user.id,
        category=category, channel_id=channel_id,
        date_from=date_from, date_to=date_to,
        unread_only=unread_only,
        limit=limit, offset=offset,
    )
    favorite_ids = await favorite_repository.get_favorite_post_ids(
        db, current_user.id, [row.Post.id for row in rows]
    )
    return [
        _to_post_out(row.Post, row.channel_username, row.channel_title,
                     cluster_size=row.cluster_size, favorite_post_ids=favorite_ids)
        for row in rows
    ]


EXPORT_LIMIT = 5000
_EXPORT_COLUMNS = [
    "id", "published_at", "channel_title", "channel_username",
    "category", "is_read", "cluster_size", "summary", "text", "telegram_url",
]


def _export_record(row) -> dict:
    post = row.Post
    username = row.channel_username
    return {
        "id": post.id,
        "published_at": post.published_at.isoformat() if post.published_at else "",
        "channel_title": row.channel_title or "",
        "channel_username": username or "",
        "category": post.category or "",
        "is_read": getattr(post, "read_at", None) is not None,
        "cluster_size": max(getattr(row, "cluster_size", 1) or 1, 1),
        "summary": post.summary or "",
        "text": post.text or "",
        "telegram_url": f"https://t.me/{username}/{post.telegram_message_id}" if username else "",
    }


@router.get("/export")
@limiter.limit("10/minute")
async def export_posts(
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    format: str = Query("csv", pattern="^(csv|json)$"),
    category: str | None = Query(None),
    channel_id: int | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    unread_only: bool = Query(False),
):
    """Download the (filtered) feed as CSV or JSON. Uses the same filters as the
    posts feed; capped at EXPORT_LIMIT rows, newest first."""
    rows = await post_repository.list_for_user(
        db, current_user.id,
        category=category, channel_id=channel_id,
        date_from=date_from, date_to=date_to, unread_only=unread_only,
        limit=EXPORT_LIMIT, offset=0,
    )
    records = [_export_record(r) for r in rows]

    if format == "json":
        body = json.dumps(records, ensure_ascii=False, indent=2)
        media, ext = "application/json", "json"
    else:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=_EXPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(records)
        body = buf.getvalue()
        media, ext = "text/csv", "csv"

    return Response(
        content=body,
        media_type=f"{media}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="sumpoint-posts.{ext}"'},
    )


@router.get("/unread-count")
async def unread_count(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    return {"count": await post_repository.count_unread(db, current_user.id)}


@router.post("/mark-read")
async def mark_posts_read(
    data: MarkReadIn,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    n = await post_repository.mark_read(db, current_user.id, data.post_ids)
    return {"marked": n}


@router.post("/mark-all-read")
async def mark_all_posts_read(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    category: str | None = Query(None),
    channel_id: int | None = Query(None),
):
    n = await post_repository.mark_all_read(
        db, current_user.id, category=category, channel_id=channel_id
    )
    return {"marked": n}


@router.get("/cluster/{cluster_id}", response_model=list[ClusterMember])
async def cluster_members(
    cluster_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Sources (posts) that make up a duplicate-cluster — powers the
    "также в N каналах" popover in the feed."""
    rows = await post_repository.get_cluster_members(db, current_user.id, cluster_id)
    return [
        ClusterMember(
            id=r.id,
            channel_id=r.channel_id,
            telegram_message_id=r.telegram_message_id,
            published_at=r.published_at,
            summary=r.summary,
            channel_username=r.channel_username,
            channel_title=r.channel_title,
        )
        for r in rows
    ]


@router.get("/search", response_model=list[PostOut])
@limiter.limit("30/minute")
async def search_posts(
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    q: str = Query(..., min_length=2),
    limit: int = Query(20, le=100),
):
    rows = await post_repository.keyword_search(db, current_user.id, q, limit=limit)
    favorite_ids = await favorite_repository.get_favorite_post_ids(
        db, current_user.id, [row.Post.id for row in rows]
    )
    return [
        _to_post_out(row.Post, row.channel_username, row.channel_title, favorite_post_ids=favorite_ids)
        for row in rows
    ]


@router.get("/semantic-search", response_model=list[PostOut])
@limiter.limit("20/minute")
async def semantic_search_posts(
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    q: str = Query(..., min_length=2),
    limit: int = Query(20, le=100),
):
    """Semantic search: embed query with BGE-M3 via Ollama, then pgvector cosine search."""
    embedding = await generate_embedding(q)
    rows = await post_repository.semantic_search(db, current_user.id, embedding, limit=limit)
    favorite_ids = await favorite_repository.get_favorite_post_ids(
        db, current_user.id, [row.id for row in rows]
    )

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
            read_at=row.read_at,
        )
        results.append(
            _to_post_out(
                post, row.channel_username, row.channel_title,
                similarity=round(float(row.similarity), 4),
                favorite_post_ids=favorite_ids,
            )
        )
    return results
