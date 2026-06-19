"""Channel management endpoints."""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.channel import Channel
from app.schemas.channel import ChannelCreate, ChannelOut
from app.api.deps import CurrentUser

router = APIRouter(prefix="/channels", tags=["channels"])


@router.get("/", response_model=list[ChannelOut])
async def list_channels(current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Channel).where(Channel.user_id == current_user.id))).scalars().all()
    return rows


@router.post("/", response_model=ChannelOut, status_code=status.HTTP_201_CREATED)
async def add_channel(body: ChannelCreate, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    telegram_id = body.telegram_id
    username = body.username
    title = body.title

    # Resolve username → telegram_id via worker (never from API container)
    if not telegram_id and username:
        from app.tasks.digest_tasks import resolve_channel_username
        try:
            result = await run_in_threadpool(
                lambda: resolve_channel_username.apply_async(args=[current_user.id, username]).get(timeout=30)
            )
            if result:
                telegram_id = result["telegram_id"]
                title = result.get("title") or title or username
                username = result.get("username") or username
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot resolve channel: {e}")

    if not telegram_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provide telegram_id or username")

    existing = (
        await db.execute(
            select(Channel).where(
                Channel.user_id == current_user.id,
                Channel.telegram_id == telegram_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Channel already added")

    ch = Channel(
        user_id=current_user.id,
        telegram_id=telegram_id,
        username=username,
        title=title or username or str(telegram_id),
    )
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


@router.post("/import", status_code=status.HTTP_200_OK)
async def import_subscribed_channels(current_user: CurrentUser):
    """Import all subscribed Telegram channels via worker (avoids dual-IP session conflict)."""
    from app.tasks.digest_tasks import import_channels_for_user
    try:
        result = await run_in_threadpool(
            lambda: import_channels_for_user.apply_async(args=[current_user.id]).get(timeout=120)
        )
        if "error" in result:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Telegram error: {result['error']}")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED)
async def sync_subscriptions(current_user: CurrentUser):
    """Trigger a background fetch of the user's Telegram subscriptions."""
    from app.tasks.digest_tasks import fetch_all_channels
    fetch_all_channels.delay()
    return {"message": "Sync started"}
