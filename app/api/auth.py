"""
Telegram Login Widget auth (GET/POST /auth/telegram)
+ Mini App auth (POST /auth/telegram/miniapp)
+ Magic Link auth (POST /auth/telegram/magic-link/request, GET .../verify)
"""
import hashlib
import hmac
import json
import time
import uuid
from datetime import timedelta
from typing import Annotated
from urllib.parse import parse_qs

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWTError as JWTError
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.constants import (
    AUTH_FRESHNESS_SECONDS,
    MAGIC_LINK_TTL_MINUTES,
    TOKEN_EXPIRE_SECONDS,
)
from app.constants import (
    JWT_ALGORITHM as ALGORITHM,
)
from app.database import get_db
from app.models.magic_link import MagicLink
from app.models.user import User
from app.rate_limit import limiter
from app.repositories import user_repository
from app.utils.time import utcnow

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()
_bearer = HTTPBearer(auto_error=False)


@router.get("/config")
async def public_config():
    """Public, non-sensitive config the frontend needs at load time."""
    return {
        "bot_username": settings.telegram_bot_username,
        "app_base_url": settings.app_base_url,
    }


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
    if abs(time.time() - data.auth_date) > AUTH_FRESHNESS_SECONDS:
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
    user = await user_repository.get_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


@router.get("/telegram")
@limiter.limit("10/minute")
async def telegram_login_get(
    request: Request,
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
    user = await user_repository.get_or_create(
        db, data.id,
        first_name=data.first_name, last_name=data.last_name, username=data.username,
    )
    token = _create_jwt(user.id)
    return {"access_token": token, "token_type": "bearer"}


# ── Mini App ──────────────────────────────────────────────────────────────────


class MiniAppAuthData(BaseModel):
    init_data: str  # raw initData string from Telegram.WebApp.initData


def _verify_webapp_init_data(init_data: str) -> dict | None:
    """Verify Telegram Mini App initData and return parsed user dict, or None."""
    if not init_data:
        return None

    parsed = parse_qs(init_data)
    # Convert parse_qs list values back to scalar strings
    fields = {k: v[-1] for k, v in parsed.items()}

    received_hash = fields.pop("hash", None)
    if not received_hash:
        return None

    # Build data_check_string: sorted keys, \n-separated
    data_check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields.keys()))

    # secret_key = HMAC-SHA256(bot_token, "WebAppData")
    secret = hmac.new(
        key="WebAppData".encode(),
        msg=settings.telegram_bot_token.encode(),
        digestmod=hashlib.sha256,
    ).digest()

    expected = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, received_hash):
        return None

    # Extract user data from the "user" field (JSON string)
    user_raw = fields.get("user")
    if not user_raw:
        return None
    try:
        user_data = json.loads(user_raw)
    except json.JSONDecodeError:
        return None

    # Check auth_date freshness (within 24h)
    auth_date = int(fields.get("auth_date", 0))
    if abs(time.time() - auth_date) > 86400:
        return None

    return user_data


@router.post("/telegram/miniapp")
@limiter.limit("10/minute")
async def miniapp_login(request: Request, data: MiniAppAuthData, db: AsyncSession = Depends(get_db)):
    """Login via Telegram Mini App (initData verification)."""
    user_data = _verify_webapp_init_data(data.init_data)
    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Telegram initData",
        )

    tid = user_data.get("id")
    if not tid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing user id")

    user = await user_repository.get_or_create(
        db, tid,
        first_name=user_data.get("first_name", ""),
        last_name=user_data.get("last_name"),
        username=user_data.get("username"),
    )
    token = _create_jwt(user.id)
    return {"access_token": token, "token_type": "bearer"}


# ── Magic Link ────────────────────────────────────────────────────────────────


class MagicLinkRequest(BaseModel):
    username: str  # Telegram @username (without @)


async def _send_telegram_message(chat_id: int, text: str) -> bool:
    """Send a message via Telegram Bot API. Returns True on success."""
    import logging

    import httpx
    logger = logging.getLogger("sumpoint.auth")
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
            })
            logger.info(f"Telegram sendMessage chat_id={chat_id} status={resp.status_code} body={resp.text[:200]}")
            return resp.status_code == 200
    except Exception as exc:
        # Don't log str(exc) — httpx exceptions may embed the request URL,
        # which contains the bot token.
        logger.error(f"Telegram sendMessage failed: chat_id={chat_id} error_type={type(exc).__name__}")
        return False


@router.post("/telegram/magic-link/request")
@limiter.limit("5/minute")
async def request_magic_link(request: Request, data: MagicLinkRequest, db: AsyncSession = Depends(get_db)):
    """Request a one-time login link sent via Telegram bot."""
    # Generic response regardless of whether the user/chat exists, to avoid
    # leaking which usernames are registered (user enumeration).
    generic_message = {
        "message": f"Если этот аккаунт активирован в @{settings.telegram_bot_username}, ссылка для входа отправлена в Telegram."
    }
    try:
        username = data.username.strip().lstrip("@")

        user = await user_repository.get_by_username(db, username)
        if not user or not user.chat_id:
            return generic_message

        expires_at = utcnow() + timedelta(minutes=MAGIC_LINK_TTL_MINUTES)
        # Generate the token upfront (rather than relying on the column default,
        # which only fires on flush) so we can send it and persist the row only
        # if the send actually succeeds — avoids ever committing a link the
        # user never received.
        magic = MagicLink(user_id=user.id, expires_at=expires_at, token=uuid.uuid4().hex)

        login_url = f"{settings.app_base_url}/?token={magic.token}"
        sent = await _send_telegram_message(
            user.chat_id,
            f"🔗 <b>Ссылка для входа в SumPoint</b>\n\n"
            f"<a href=\"{login_url}\">Нажмите сюда, чтобы войти</a>\n\n"
            f"Ссылка действительна {MAGIC_LINK_TTL_MINUTES} минут.",
        )

        if sent:
            db.add(magic)
            await db.flush()

        return generic_message
    except HTTPException:
        raise
    except Exception:
        return generic_message


@router.get("/telegram/magic-link/verify")
@limiter.limit("10/minute")
async def verify_magic_link(request: Request, token: str = Query(...), db: AsyncSession = Depends(get_db)):
    """Verify a magic link token and return a JWT."""
    import logging
    try:
        result = await db.execute(
            select(MagicLink).where(
                MagicLink.token == token,
                MagicLink.used.is_(False),
                MagicLink.expires_at > utcnow(),
            )
        )
        magic = result.scalar_one_or_none()

        if not magic:
            raise HTTPException(
                status_code=400,
                detail="Ссылка недействительна или истекла. Запросите новую.",
            )

        magic.used = True
        await db.flush()

        user = await user_repository.get_by_id(db, magic.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден.")

        jwt_token = _create_jwt(user.id)
        return {"access_token": jwt_token, "token_type": "bearer"}
    except HTTPException:
        raise
    except Exception:
        # Don't leak internal error detail to the client.
        logging.getLogger("sumpoint.auth").exception("verify_magic_link failed")
        raise HTTPException(status_code=500, detail="Внутренняя ошибка. Попробуйте позже.")


@router.post("/telegram")
@limiter.limit("10/minute")
async def telegram_login(request: Request, data: TelegramAuthData, db: AsyncSession = Depends(get_db)):
    if not _verify_telegram_hash(data):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Telegram auth data")

    user = await user_repository.get_or_create(
        db, data.id,
        first_name=data.first_name, last_name=data.last_name, username=data.username,
    )
    token = _create_jwt(user.id)
    return {"access_token": token, "token_type": "bearer"}

