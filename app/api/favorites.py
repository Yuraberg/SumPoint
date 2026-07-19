"""Favorites (bookmarks) for posts and calendar events."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.database import get_db
from app.models.favorite import WHOLE_POST
from app.repositories import favorite_repository
from app.schemas.post import PostOut
from app.services.calendar_service import get_favorite_events

router = APIRouter(prefix="/favorites", tags=["favorites"])


class ToggleFavoriteIn(BaseModel):
    post_id: int
    event_index: int = WHOLE_POST


@router.post("/toggle")
async def toggle_favorite(
    data: ToggleFavoriteIn,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    try:
        is_favorite = await favorite_repository.toggle(
            db, current_user.id, data.post_id, data.event_index
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Post or event not found")
    return {"is_favorite": is_favorite}


@router.get("/posts", response_model=list[PostOut])
async def list_favorite_posts(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    category: str | None = Query(None),
):
    rows = await favorite_repository.list_favorite_posts(db, current_user.id, category=category)
    return [
        PostOut(
            id=row.Post.id,
            channel_id=row.Post.channel_id,
            telegram_message_id=row.Post.telegram_message_id,
            text=row.Post.text,
            published_at=row.Post.published_at,
            summary=row.Post.summary,
            category=row.Post.category,
            is_ad=row.Post.is_ad,
            events=row.Post.events,
            channel_username=row.channel_username,
            channel_title=row.channel_title,
            is_read=row.Post.read_at is not None,
            is_favorite=True,
            cluster_id=row.Post.cluster_id,
        )
        for row in rows
    ]


@router.get("/events")
async def list_favorite_events(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    return {"events": await get_favorite_events(db, current_user.id)}
