"""Shared rate limiter instance, imported by both app.main and API routers
to avoid a circular import between them."""
from slowapi import Limiter
from slowapi.util import get_remote_address


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


limiter = Limiter(key_func=_client_ip)
