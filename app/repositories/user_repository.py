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
    is_approved: bool = False,
) -> User:
    """Return the existing user or create one, flushing so ``user.id`` is set.

    Consolidates the near-identical user-creation blocks that lived in the three
    auth endpoints and the bot ``/start`` handler. Existing rows are refreshed
    with any newly supplied ``first_name`` / ``username`` / ``chat_id`` so a
    login always keeps the display name, DM channel, and handle current with
    Telegram. The caller owns the commit.

    ``is_approved`` only applies to a brand-new row — the caller (which has
    access to Settings.owner_telegram_id_set and any invite code) decides
    whether this signup should be auto-approved; an existing user's approval
    status is never touched here.
    """
    user = await get_by_id(db, user_id)
    if user is None:
        user = User(
            id=user_id,
            first_name=first_name or "User",
            last_name=last_name,
            username=username,
            chat_id=chat_id,
            is_approved=is_approved,
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


async def login_or_signup(
    db: AsyncSession,
    user_id: int,
    *,
    first_name: str = "",
    last_name: str | None = None,
    username: str | None = None,
    chat_id: int | None = None,
    invite_code: str | None = None,
) -> User:
    """The shared entry point for every place a Telegram login can create a
    user: web auth endpoints and the bot's /start handler. A brand-new signup
    is auto-approved only via the owner allowlist or a valid invite code
    (invite_repository.resolve_signup_approval, which also consumes the
    code); an existing user's approval status and invite-code use are never
    touched by logging in again.
    """
    from app.repositories import invite_repository  # local import: avoids a
    # module-load-time cycle (invite_repository -> app.config is fine, but
    # keeping the cross-repository edge local makes the dependency direction
    # obvious at the call site).

    existing = await get_by_id(db, user_id)
    is_approved = False
    if existing is None:
        is_approved = await invite_repository.resolve_signup_approval(db, user_id, invite_code)
    return await get_or_create(
        db, user_id,
        first_name=first_name, last_name=last_name, username=username,
        chat_id=chat_id, is_approved=is_approved,
    )


async def get_digest_subscribers(db: AsyncSession, slot: str) -> list[User]:
    """Users opted in to the given digest slot ('morning' | 'evening').

    Requires ``chat_id`` to be set: it's only populated by the bot's /start
    handler, never by the web login flows (Login Widget / magic link / Mini
    App). ``digest_morning`` defaults to True for every new user regardless of
    which flow they signed up through, so a web-only user who never messaged
    the bot would otherwise be queried here every single slot and fail with
    Telegram's "Chat not found" — permanently, since they can't receive a DM
    from a chat that doesn't exist yet.
    """
    field = User.digest_morning if slot == "morning" else User.digest_evening
    return (
        await db.execute(select(User).where(field.is_(True), User.chat_id.is_not(None)))
    ).scalars().all()
