"""FastAPI application entry point."""
import logging
import os
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.router import api_router
from app.config import get_settings
from app.logging import request_id_var
from app.rate_limit import limiter

_settings = get_settings()

# Content-Security-Policy. script-src omits 'unsafe-inline' so an injected
# <script> (or stolen-then-replayed inline handler) can't run and exfiltrate the
# localStorage JWT — the frontend was refactored to external files + delegated
# listeners to satisfy this. Telegram's Login Widget needs its script host and
# an iframe (oauth.telegram.org). style-src keeps 'unsafe-inline' because the
# markup uses style="" attributes and CSS injection is far lower risk.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' https://telegram.org https://oauth.telegram.org; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https://telegram.org; "
    "connect-src 'self'; "
    "frame-src https://oauth.telegram.org https://telegram.org; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "object-src 'none'"
)
_SECURITY_HEADERS = {
    "Content-Security-Policy": _CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    # Ignored by browsers over plain HTTP; takes effect once behind HTTPS.
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
}

# ── Logging configuration ────────────────────────────────────────────
# Development: human-readable text logs
# Production: JSON logs (parseable by Loki, Datadog, etc.)
if _settings.debug:
    logging.basicConfig(
        level=getattr(logging, _settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
else:
    from app.logging import setup_json_logging
    setup_json_logging(level=getattr(logging, _settings.log_level.upper(), logging.WARNING))
# Keep third-party libraries quiet unless LOG_LEVEL is DEBUG
if _settings.log_level.upper() not in ("DEBUG",):
    for lib in ("httpx", "httpcore", "openai", "sqlalchemy.engine", "celery"):
        logging.getLogger(lib).setLevel(logging.WARNING)

# ── Sentry (optional error tracking) ──────────────────────────────────
# Set SENTRY_DSN in .env to activate. Without it, Sentry is a no-op.
# Get a DSN at https://sentry.io → Create Project → FastAPI.
if _settings.sentry_dsn:
    import sentry_sdk
    sentry_sdk.init(
        dsn=_settings.sentry_dsn,
        traces_sample_rate=0.1,  # capture 10% of transactions for perf
        environment="production" if not _settings.debug else "development",
        send_default_pii=False,
    )
    logging.getLogger("sentry_sdk").setLevel(logging.WARNING)

# ── App ──────────────────────────────────────────────────────────────

# Schema is owned exclusively by Alembic migrations (see CLAUDE.md —
# `alembic upgrade head` runs before the app starts in both local dev and
# Docker). The app no longer creates/migrates tables itself at startup.
app = FastAPI(
    title="SumPoint",
    description="Intelligent Telegram content processing — AI digest, classification & event extraction",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.state.limiter = limiter
# Enforces the limiter's default_limits on every route without its own
# @limiter.limit (a global anti-abuse floor); decorated routes keep their limit.
app.add_middleware(SlowAPIMiddleware)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_access_logger = logging.getLogger("app.access")


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Tag every request with an id so its log lines (and any exception
    traceback) can be correlated back to a single user report, and expose it
    in the response so the frontend/user can quote it back to us."""
    req_id = str(uuid.uuid4())
    token = request_id_var.set(req_id)
    started = time.monotonic()
    try:
        response = await call_next(request)
        duration_ms = round((time.monotonic() - started) * 1000, 1)
        response.headers["X-Request-ID"] = req_id
        for header, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        _access_logger.info(
            "%s %s %s %sms", request.method, request.url.path, response.status_code, duration_ms
        )
        return response
    finally:
        request_id_var.reset(token)

# Production safeguard: warn if CORS_ORIGINS still points to localhost
if not _settings.debug:
    localhost_origins = [o for o in _settings.cors_origins if "localhost" in o or "127.0.0.1" in o]
    if localhost_origins:
        import logging
        _log = logging.getLogger("uvicorn")
        _log.warning(
            "CORS_ORIGINS contains localhost in production mode: %s. "
            "Set CORS_ORIGINS to your frontend domain(s) before launch.",
            localhost_origins,
        )
    # APP_BASE_URL builds the login link sent via the Telegram bot (magic
    # link) and the Mini App URL. Left at its localhost default, that link is
    # unreachable from a user's phone — the bot message arrives but the link
    # in it goes nowhere, which reads as "there's no link".
    if "localhost" in _settings.app_base_url or "127.0.0.1" in _settings.app_base_url:
        import logging
        logging.getLogger("uvicorn").warning(
            "APP_BASE_URL is still %r in production mode. The Telegram magic-link "
            "login button will point at an unreachable address — set APP_BASE_URL "
            "to your public domain (e.g. https://sum.example.com).",
            _settings.app_base_url,
        )

app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
@limiter.exempt
async def health():
    return {"status": "ok"}


# Serve frontend SPA — catch-all must be LAST so API routes take priority
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(frontend_dir):
    @app.get("/{full_path:path}")
    @limiter.exempt
    async def serve_spa(full_path: str):
        """Serve frontend files, falling back to index.html for SPA routing."""
        # Prevent directory traversal (including absolute-path escapes)
        safe_path = os.path.normpath(full_path).lstrip("/").lstrip("\\")
        if safe_path.startswith(".."):
            raise HTTPException(status_code=404, detail="Not Found")

        base_dir = os.path.realpath(frontend_dir)
        file_path = os.path.realpath(os.path.join(base_dir, safe_path))
        if not (file_path == base_dir or file_path.startswith(base_dir + os.sep)):
            raise HTTPException(status_code=404, detail="Not Found")
        if os.path.isfile(file_path):
            return FileResponse(file_path)

        # SPA fallback — return index.html for any unknown path
        index_path = os.path.join(frontend_dir, "index.html")
        if os.path.isfile(index_path):
            return FileResponse(index_path)

        raise HTTPException(status_code=404, detail="Not Found")
