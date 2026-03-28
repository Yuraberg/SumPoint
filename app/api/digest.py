"""Digest and calendar endpoints."""
from typing import Annotated
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.api.auth import get_current_user
from app.services.digest_service import build_user_digest
from app.services.calendar_service import get_upcoming_events

router = APIRouter(prefix="/digest", tags=["digest"])
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get("/")
async def get_digest(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    hours: int = Query(24, ge=1, le=72),
):
    """Build and return a fresh digest for the authenticated user."""
    return await build_user_digest(db, current_user.id, hours=hours)


@router.get("/events")
async def get_events(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    days_ahead: int = Query(7, ge=1, le=30),
):
    """Return upcoming calendar events extracted from posts."""
    events = await get_upcoming_events(db, current_user.id, days_ahead=days_ahead)
    return {"events": events}
