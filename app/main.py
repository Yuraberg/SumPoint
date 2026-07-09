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

from app.api.router import api_router
from app.config import get_settings
from app.logging import request_id_var
from app.rate_limit import limiter

_settings = get_settings()

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
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.limiter = limiter
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

app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok"}


# Serve frontend SPA — catch-all must be LAST so API routes take priority
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(frontend_dir):
    @app.get("/{full_path:path}")
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
