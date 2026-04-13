"""
Telegram Login Widget authentication.

Flow:
  1. Frontend collects the widget data hash from Telegram.
  2. POST /auth/telegram  →  verifies HMAC, upserts User, returns JWT.
"""
import hashlib
import hmac
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.user import User
from sqlalchemy import select

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()
_bearer = HTTPBearer(auto_error=False)

ALGORITHM = "HS256"
TOKEN_EXPIRE_SECONDS = 60 * 60 * 24 * 7  # 7 days


class TelegramAuthData(BaseModel):
    id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None
    auth_date: int
    hash: str


def _verify_telegram_hash(data: TelegramAuthData) -> bool:
    """Verify the hash provided by Telegram Login Widget."""
    fields = {k: v for k, v in data.model_dump().items() if k != "hash" and v is not None}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hashlib.sha256(settings.telegram_bot_token.encode()).digest()
    expected = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    # Also check auth_date freshness (within 24 h)
    if abs(time.time() - data.auth_date) > 86400:
        return False
    return hmac.compare_digest(expected, data.hash)


def _create_jwt(user_id: int) -> str:
    payload = {"sub": str(user_id), "exp": int(time.time()) + TOKEN_EXPIRE_SECONDS}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: AsyncSession = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = jwt.decode(credentials.credentials, settings.secret_key, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


@router.get("/telegram")
async def telegram_login_get(
    id: int = Query(...),
    first_name: str = Query(...),
    auth_date: int = Query(...),
    hash: str = Query(...),
    last_name: str | None = Query(None),
    username: str | None = Query(None),
    photo_url: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    data = TelegramAuthData(
        id=id, first_name=first_name, last_name=last_name,
        username=username, photo_url=photo_url, auth_date=auth_date, hash=hash,
    )
    if not _verify_telegram_hash(data):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Telegram auth data")
    user = (await db.execute(select(User).where(User.id == data.id))).scalar_one_or_none()
    if not user:
        user = User(id=data.id, first_name=data.first_name, last_name=data.last_name, username=data.username)
        db.add(user)
        await db.flush()
    token = _create_jwt(user.id)
    return {"access_token": token, "token_type": "bearer"}


@router.post("/telegram")
async def telegram_login(data: TelegramAuthData, db: AsyncSession = Depends(get_db)):
    if not _verify_telegram_hash(data):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Telegram auth data")

    user = (await db.execute(select(User).where(User.id == data.id))).scalar_one_or_none()
    if not user:
        user = User(
            id=data.id,
            first_name=data.first_name,
            last_name=data.last_name,
            username=data.username,
        )
        db.add(user)
        await db.flush()

    token = _create_jwt(user.id)
    return {"access_token": token, "token_type": "bearer"}
