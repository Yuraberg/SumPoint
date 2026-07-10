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
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWTError as JWTError
from pydantic import BaseModel
from sqlalchemy import update
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

# Session cookie holding the JWT. HttpOnly so JavaScript (and therefore an
# injected XSS payload) can never read it — the token is no longer kept in
# localStorage. SameSite=Lax means the browser won't attach it to cross-site
# POST/DELETE requests, which neutralises CSRF for the state-changing API
# without a separate token (all GETs are read-only). Secure is off only in
# local debug so http://localhost works; production is HTTPS behind Caddy.
SESSION_COOKIE = "sp_session"


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=TOKEN_EXPIRE_SECONDS,
        httponly=True,
        secure=not settings.debug,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE, path="/")


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


def _create_jwt(user: User) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user.id),
        # revocation: must match the user's current version. `or 0` guards a
        # transient (un-flushed) instance whose column default hasn't fired.
        "tv": user.token_version or 0,
        "iat": now,
        "exp": now + TOKEN_EXPIRE_SECONDS,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: AsyncSession = Depends(get_db),
) -> User:
    # Prefer the HttpOnly session cookie (SPA); fall back to a Bearer header so
    # programmatic/API clients still work.
    raw_token = request.cookies.get(SESSION_COOKIE)
    if not raw_token and credentials:
        raw_token = credentials.credentials
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = jwt.decode(raw_token, settings.secret_key, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = await user_repository.get_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    # A token minted before the user bumped token_version (logout-everywhere /
    # revoke-on-compromise) is no longer valid. Absent claim → treat as 0 so
    # tokens minted before this feature keep working until they expire.
    if payload.get("tv", 0) != user.token_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked")
    return user


@router.get("/me")
async def me(current_user: Annotated[User, Depends(get_current_user)]):
    """Who am I — the SPA calls this on load to decide login vs app (the JWT
    lives in an HttpOnly cookie it can't read itself), and whether to show the
    "pending approval" screen instead of the app for a not-yet-approved user."""
    from app.api.deps import is_effectively_approved

    return {
        "id": current_user.id,
        "first_name": current_user.first_name,
        "username": current_user.username,
        "is_approved": is_effectively_approved(current_user),
        "is_owner": current_user.id in settings.owner_telegram_id_set,
    }


@router.post("/logout")
async def logout(response: Response):
    """Clear the session cookie (this device only). No auth required — clearing
    an already-invalid cookie is harmless."""
    _clear_session_cookie(response)
    return {"message": "Вы вышли."}


@router.get("/telegram")
@limiter.limit("10/minute")
async def telegram_login_get(
    request: Request,
    response: Response,
    id: int = Query(...),
    first_name: str = Query(...),
    auth_date: int = Query(...),
    hash: str = Query(...),
    last_name: str | None = Query(None),
    username: str | None = Query(None),
    photo_url: str | None = Query(None),
    invite_code: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    data = TelegramAuthData(
        id=id, first_name=first_name, last_name=last_name,
        username=username, photo_url=photo_url, auth_date=auth_date, hash=hash,
    )
    if not _verify_telegram_hash(data):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Telegram auth data")
    user = await user_repository.login_or_signup(
        db, data.id,
        first_name=data.first_name, last_name=data.last_name, username=data.username,
        invite_code=invite_code,
    )
    token = _create_jwt(user)
    _set_session_cookie(response, token)
    return {"access_token": token, "token_type": "bearer"}


# ── Mini App ──────────────────────────────────────────────────────────────────


class MiniAppAuthData(BaseModel):
    init_data: str  # raw initData string from Telegram.WebApp.initData
    invite_code: str | None = None


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
async def miniapp_login(request: Request, response: Response, data: MiniAppAuthData, db: AsyncSession = Depends(get_db)):
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

    user = await user_repository.login_or_signup(
        db, tid,
        first_name=user_data.get("first_name", ""),
        last_name=user_data.get("last_name"),
        username=user_data.get("username"),
        invite_code=data.invite_code,
    )
    token = _create_jwt(user)
    _set_session_cookie(response, token)
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
            ok = resp.status_code == 200
            # WARNING (not INFO) on failure so it's visible at the default
            # production LOG_LEVEL — a bad HTML entity (e.g. an unreachable
            # APP_BASE_URL scheme) makes Telegram reject the whole message,
            # which otherwise fails completely silently.
            if ok:
                logger.debug(f"Telegram sendMessage chat_id={chat_id} status={resp.status_code}")
            else:
                logger.warning(
                    f"Telegram sendMessage failed chat_id={chat_id} "
                    f"status={resp.status_code} body={resp.text[:300]}"
                )
            return ok
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
        # The link text IS the URL (not a generic "click here") so it's visible
        # and copy-pasteable even if a client fails to render the <a> as
        # clickable — e.g. because APP_BASE_URL was misconfigured to a
        # non-public host, which some Telegram clients decline to auto-link.
        sent = await _send_telegram_message(
            user.chat_id,
            f"🔗 <b>Ссылка для входа в SumPoint</b>\n\n"
            f"<a href=\"{login_url}\">{login_url}</a>\n\n"
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
async def verify_magic_link(request: Request, response: Response, token: str = Query(...), db: AsyncSession = Depends(get_db)):
    """Verify a magic link token and return a JWT."""
    import logging
    try:
        # Atomic claim: mark used only if still unused, so two concurrent
        # verifies of the same link can't both succeed (double-spend). The
        # UPDATE ... WHERE used=false RETURNING lets exactly one caller win.
        result = await db.execute(
            update(MagicLink)
            .where(
                MagicLink.token == token,
                MagicLink.used.is_(False),
                MagicLink.expires_at > utcnow(),
            )
            .values(used=True)
            .returning(MagicLink.user_id)
        )
        row = result.first()

        if not row:
            raise HTTPException(
                status_code=400,
                detail="Ссылка недействительна или истекла. Запросите новую.",
            )
        await db.flush()

        user = await user_repository.get_by_id(db, row.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден.")

        jwt_token = _create_jwt(user)
        _set_session_cookie(response, jwt_token)
        return {"access_token": jwt_token, "token_type": "bearer"}
    except HTTPException:
        raise
    except Exception:
        # Don't leak internal error detail to the client.
        logging.getLogger("sumpoint.auth").exception("verify_magic_link failed")
        raise HTTPException(status_code=500, detail="Внутренняя ошибка. Попробуйте позже.")


@router.post("/logout-all")
async def logout_all(
    current_user: Annotated[User, Depends(get_current_user)],
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Revoke every JWT issued to the caller (this device included) by bumping
    their token_version. Use after a suspected token/device compromise."""
    current_user.token_version = (current_user.token_version or 0) + 1
    await db.flush()
    _clear_session_cookie(response)
    return {"message": "Все сессии завершены. Войдите заново."}


class RedeemInviteIn(BaseModel):
    code: str


@router.post("/redeem-invite")
@limiter.limit("10/minute")
async def redeem_invite(
    request: Request,
    body: RedeemInviteIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    """Let an authenticated-but-pending user unlock their own account with an
    invite code from the web pending screen (identity alone gets you here via
    get_current_user; approval is exactly what's being granted)."""
    from app.repositories import invite_repository

    if current_user.is_approved:
        return {"is_approved": True}
    if not await invite_repository.try_consume(db, body.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Код недействителен или уже использован.")
    current_user.is_approved = True
    await db.flush()
    return {"is_approved": True}


@router.post("/telegram")
@limiter.limit("10/minute")
async def telegram_login(
    request: Request, response: Response, data: TelegramAuthData,
    invite_code: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    if not _verify_telegram_hash(data):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Telegram auth data")

    user = await user_repository.login_or_signup(
        db, data.id,
        first_name=data.first_name, last_name=data.last_name, username=data.username,
        invite_code=invite_code,
    )
    token = _create_jwt(user)
    _set_session_cookie(response, token)
    return {"access_token": token, "token_type": "bearer"}

