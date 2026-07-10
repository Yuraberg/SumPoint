"""Owner-only access-control admin: pending-user queue and invite codes."""
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models.invite_code import InviteCode
from app.models.user import User
from app.repositories import invite_repository

router = APIRouter(prefix="/admin", tags=["admin"])


async def require_owner(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    """Every route in this router is owner-only — pending/approved users get
    a plain 403, same as any other endpoint they're not allowed to touch."""
    if current_user.id not in get_settings().owner_telegram_id_set:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Только для владельца сервиса.")
    return current_user


OwnerUser = Annotated[User, Depends(require_owner)]


class PendingUserOut(BaseModel):
    id: int
    username: str | None
    first_name: str
    created_at: datetime

    model_config = {"from_attributes": True}


class InviteOut(BaseModel):
    id: int
    code: str
    max_uses: int
    uses: int
    note: str | None
    created_at: datetime
    expires_at: datetime | None

    model_config = {"from_attributes": True}


class InviteCreateIn(BaseModel):
    max_uses: int = 1
    expires_in_days: int | None = None
    note: str | None = None


@router.get("/pending-users", response_model=list[PendingUserOut])
async def list_pending_users(_owner: OwnerUser, db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(User).where(User.is_approved.is_(False)).order_by(User.created_at.desc())
        )
    ).scalars().all()
    return rows


@router.post("/pending-users/{user_id}/approve", response_model=PendingUserOut)
async def approve_pending_user(user_id: int, _owner: OwnerUser, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    user.is_approved = True
    await db.flush()
    return user


@router.get("/invites", response_model=list[InviteOut])
async def list_invites(_owner: OwnerUser, db: AsyncSession = Depends(get_db)):
    return await invite_repository.list_all(db)


@router.post("/invites", response_model=InviteOut, status_code=status.HTTP_201_CREATED)
async def create_invite(body: InviteCreateIn, owner: OwnerUser, db: AsyncSession = Depends(get_db)):
    expires_at = None
    if body.expires_in_days:
        from app.utils.time import utcnow
        expires_at = utcnow() + timedelta(days=body.expires_in_days)
    return await invite_repository.create(
        db, created_by=owner.id, max_uses=max(1, body.max_uses),
        expires_at=expires_at, note=body.note,
    )


@router.delete("/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_invite(invite_id: int, _owner: OwnerUser, db: AsyncSession = Depends(get_db)):
    invite = (
        await db.execute(select(InviteCode).where(InviteCode.id == invite_id))
    ).scalar_one_or_none()
    if not invite:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Код не найден")
    await db.delete(invite)
