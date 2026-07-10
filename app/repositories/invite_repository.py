"""Invite-code queries: create, look up, and atomically consume a code."""
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.invite_code import InviteCode
from app.utils.time import utcnow


async def create(
    db: AsyncSession,
    *,
    created_by: int | None,
    max_uses: int = 1,
    expires_at: datetime | None = None,
    note: str | None = None,
) -> InviteCode:
    invite = InviteCode(created_by=created_by, max_uses=max_uses, expires_at=expires_at, note=note)
    db.add(invite)
    await db.flush()
    return invite


async def get_by_code(db: AsyncSession, code: str) -> InviteCode | None:
    return (
        await db.execute(select(InviteCode).where(InviteCode.code == code.strip().upper()))
    ).scalar_one_or_none()


def is_valid(invite: InviteCode) -> bool:
    not_expired = invite.expires_at is None or invite.expires_at >= utcnow()
    return invite.uses < invite.max_uses and not_expired


async def try_consume(db: AsyncSession, code: str) -> bool:
    """Atomically claim one use of `code`. Returns True iff a use was granted.

    UPDATE ... WHERE uses < max_uses (and not expired) is race-safe: two
    concurrent redemptions of the last remaining use can't both succeed.
    """
    stmt = (
        update(InviteCode)
        .where(
            InviteCode.code == code.strip().upper(),
            InviteCode.uses < InviteCode.max_uses,
        )
        .values(uses=InviteCode.uses + 1)
    )
    result = await db.execute(stmt)
    if result.rowcount != 1:
        return False

    # rowcount==1 confirmed a slot was claimed; still need to reject an
    # already-expired code (can't express "not expired" cleanly against a
    # nullable column in the WHERE above alongside the increment race-safely,
    # so check it post-hoc and roll back the claim if expired).
    invite = await get_by_code(db, code)
    if invite and invite.expires_at and invite.expires_at < utcnow():
        await db.execute(
            update(InviteCode).where(InviteCode.id == invite.id).values(uses=InviteCode.uses - 1)
        )
        return False
    return True


async def list_all(db: AsyncSession) -> list[InviteCode]:
    return (
        await db.execute(select(InviteCode).order_by(InviteCode.created_at.desc()))
    ).scalars().all()


async def resolve_signup_approval(db: AsyncSession, telegram_user_id: int, invite_code: str | None) -> bool:
    """Whether a brand-new signup should be auto-approved, and consume the
    invite code if that's what grants it. Shared by every place a new User
    row can be created (web login endpoints, the bot's /start handler) so the
    access-control decision lives in exactly one place.

    Owner ids always win regardless of an invite code (and don't burn one).
    """
    if telegram_user_id in get_settings().owner_telegram_id_set:
        return True
    return bool(invite_code) and await try_consume(db, invite_code)
