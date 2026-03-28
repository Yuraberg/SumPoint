"""Channel management endpoints."""
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.channel import Channel
from app.models.user import User
from app.schemas.channel import ChannelCreate, ChannelOut
from app.api.auth import get_current_user

router = APIRouter(prefix="/channels", tags=["channels"])
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get("/", response_model=list[ChannelOut])
async def list_channels(current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Channel).where(Channel.user_id == current_user.id))).scalars().all()
    return rows


@router.post("/", response_model=ChannelOut, status_code=status.HTTP_201_CREATED)
async def add_channel(body: ChannelCreate, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    existing = (
        await db.execute(
            select(Channel).where(
                Channel.user_id == current_user.id,
                Channel.telegram_id == body.telegram_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Channel already added")

    ch = Channel(user_id=current_user.id, **body.model_dump())
    db.add(ch)
    await db.flush()
    return ch


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_channel(channel_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    ch = (
        await db.execute(
            select(Channel).where(Channel.id == channel_id, Channel.user_id == current_user.id)
        )
    ).scalar_one_or_none()
    if not ch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    await db.delete(ch)


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED)
async def sync_subscriptions(current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """Trigger a background fetch of the user's Telegram subscriptions."""
    from app.tasks.digest_tasks import fetch_all_channels
    fetch_all_channels.delay()
    return {"message": "Sync started"}
