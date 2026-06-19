"""Digest and calendar endpoints."""
from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import CurrentUser
from app.services.digest_service import build_user_digest
from app.services.calendar_service import get_upcoming_events

router = APIRouter(prefix="/digest", tags=["digest"])


@router.get("/")
async def get_digest(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    hours: int = Query(24, ge=1, le=72),
):
    return await build_user_digest(db, current_user.id, hours=hours)


@router.get("/events")
async def get_events(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    days_ahead: int = Query(7, ge=1, le=365),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    event_type: str | None = Query(None),
):
    events = await get_upcoming_events(
        db, current_user.id,
        days_ahead=days_ahead,
        date_from=date_from,
        date_to=date_to,
        event_type=event_type,
    )
    return {"events": events}
