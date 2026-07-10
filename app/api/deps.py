"""Shared FastAPI dependencies for the API routers."""
from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.api.auth import get_current_user
from app.config import get_settings
from app.models.user import User


def is_effectively_approved(user: User) -> bool:
    """A user can use the app if manually/invite-approved, or if their
    Telegram id is in the live owner allowlist — checked at request time
    (not just at signup) so editing OWNER_TELEGRAM_IDS takes effect
    immediately without touching the database."""
    return user.is_approved or user.id in get_settings().owner_telegram_id_set


async def get_approved_user(user: Annotated[User, Depends(get_current_user)]) -> User:
    """Gate for every business endpoint: identity alone isn't enough, the
    account must also be approved. /auth/me and /auth/logout* deliberately use
    get_current_user directly (not this) so a pending user can still check
    their status and sign out."""
    if not is_effectively_approved(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Аккаунт ожидает одобрения владельца сервиса.",
        )
    return user


CurrentUser = Annotated[User, Depends(get_approved_user)]
