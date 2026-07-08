"""User queries and get-or-create helper."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def get_by_id(db: AsyncSession, user_id: int) -> User | None:
    return (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()


async def get_by_username(db: AsyncSession, username: str) -> User | None:
    return (
        await db.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()


async def get_or_create(
    db: AsyncSession,
    user_id: int,
    *,
    first_name: str = "",
    last_name: str | None = None,
    username: str | None = None,
    chat_id: int | None = None,
) -> User:
    """Return the existing user or create one, flushing so ``user.id`` is set.

    Consolidates the near-identical user-creation blocks that lived in the three
    auth endpoints and the bot ``/start`` handler. Existing rows are refreshed
    with any newly supplied ``first_name`` / ``username`` / ``chat_id`` so a
    login always keeps the display name, DM channel, and handle current with
    Telegram. The caller owns the commit.
    """
    user = await get_by_id(db, user_id)
    if user is None:
        user = User(
            id=user_id,
            first_name=first_name or "User",
            last_name=last_name,
            username=username,
            chat_id=chat_id,
        )
        db.add(user)
        await db.flush()
        return user

    # Refresh mutable identity fields on returning users.
    if first_name:
        user.first_name = first_name
    if username:
        user.username = username
    if chat_id is not None:
        user.chat_id = chat_id
    return user


async def get_digest_subscribers(db: AsyncSession, slot: str) -> list[User]:
    """Users opted in to the given digest slot ('morning' | 'evening')."""
    field = User.digest_morning if slot == "morning" else User.digest_evening
    return (await db.execute(select(User).where(field.is_(True)))).scalars().all()
