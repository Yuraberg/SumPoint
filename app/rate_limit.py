"""Shared rate limiter instance, imported by both app.main and API routers
to avoid a circular import between them."""
from slowapi import Limiter
from slowapi.util import get_remote_address


def _client_ip(request) -> str:
    """Real client IP, not Caddy's. The app only ever receives traffic
    through the Caddy reverse proxy, which sets X-Forwarded-For to the
    original client address — without this, get_remote_address() returns
    Caddy's container IP for every request, so all users share one
    rate-limit bucket on /auth endpoints."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=_client_ip)
