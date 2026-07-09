"""Analytics dashboard endpoints — activity over time and channel health."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.database import get_db
from app.repositories import stats_repository

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/overview")
async def stats_overview(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=180),
):
    """Everything the statistics page needs in one round-trip."""
    return {
        "totals": await stats_repository.totals(db, current_user.id),
        "per_day": await stats_repository.posts_per_day(db, current_user.id, days=days),
        "per_category": await stats_repository.posts_per_category(db, current_user.id),
        "per_channel": await stats_repository.posts_per_channel(db, current_user.id),
        "days": days,
    }


@router.get("/channel-health")
async def channel_health(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Per-channel post/unread counts, freshness and last error for the
    Channels page health panel."""
    return await stats_repository.channel_health(db, current_user.id)
