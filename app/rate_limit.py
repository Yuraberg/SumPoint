"""Shared rate limiter instance, imported by both app.main and API routers
to avoid a circular import between them."""
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_settings

_settings = get_settings()


def _client_ip(request) -> str:
    """Real client IP, not Caddy's. The app only ever receives traffic
    through the Caddy reverse proxy, which appends the address it sees to
    X-Forwarded-For — without this, get_remote_address() returns Caddy's
    container IP for every request, so all users share one rate-limit
    bucket on /auth endpoints.

    Take the LAST entry, not the first: Caddy appends the peer address it
    observed to whatever X-Forwarded-For it received, it does not overwrite
    it. A client can freely set X-Forwarded-For itself, so the first entry
    is attacker-controlled (`curl -H "X-Forwarded-For: 1.1.1.1"` would let
    an attacker rotate through fake IPs to dodge the limiter entirely). The
    last entry is the one Caddy itself appended from the raw TCP connection,
    which the client can't forge.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return get_remote_address(request)


# Redis-backed so limits are shared across worker processes and survive a
# restart (the in-memory default reset every deploy and gave each uvicorn
# worker its own bucket). ``default_limits`` is a global safety net applied to
# any route without its own @limiter.limit; per-route decorators still win.
# ``swallow_errors`` fails open — a Redis blip must not 500 every request or
# lock users out of auth.
limiter = Limiter(
    key_func=_client_ip,
    storage_uri=_settings.redis_url,
    default_limits=["240/minute"],
    swallow_errors=True,
)
