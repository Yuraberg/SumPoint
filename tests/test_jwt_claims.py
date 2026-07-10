"""JWT minting: the token carries the claims get_current_user relies on for
revocation (tv) and issue time (iat). Pure — no DB."""
import time

import jwt

from app.api.auth import _create_jwt, settings
from app.constants import JWT_ALGORITHM, TOKEN_EXPIRE_SECONDS
from app.models.user import User


def test_create_jwt_embeds_sub_tv_iat_exp():
    user = User(id=42, first_name="Alice")
    user.token_version = 3
    before = int(time.time())
    token = _create_jwt(user)
    payload = jwt.decode(token, settings.secret_key, algorithms=[JWT_ALGORITHM])

    assert payload["sub"] == "42"
    assert payload["tv"] == 3
    assert before <= payload["iat"] <= int(time.time())
    assert payload["exp"] == payload["iat"] + TOKEN_EXPIRE_SECONDS


def test_create_jwt_defaults_token_version_zero():
    user = User(id=7, first_name="Bob")  # token_version unset → model default 0
    token = _create_jwt(user)
    payload = jwt.decode(token, settings.secret_key, algorithms=[JWT_ALGORITHM])
    assert payload["tv"] == 0


def test_session_cookie_has_secure_flags():
    """The session cookie must be HttpOnly + SameSite=Lax so JS can't read it
    and it isn't attached to cross-site POST/DELETE (CSRF)."""
    from fastapi import Response

    from app.api.auth import SESSION_COOKIE, _set_session_cookie

    resp = Response()
    _set_session_cookie(resp, "jwt-value")
    header = resp.headers["set-cookie"].lower()
    assert f"{SESSION_COOKIE}=jwt-value" in resp.headers["set-cookie"]
    assert "httponly" in header
    assert "samesite=lax" in header
    assert "path=/" in header

