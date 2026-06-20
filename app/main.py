"""FastAPI application entry point."""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
import os

from app.api.router import api_router
from app.config import get_settings
from app.rate_limit import limiter

# Schema is owned exclusively by Alembic migrations (see CLAUDE.md —
# `alembic upgrade head` runs before the app starts in both local dev and
# Docker). The app no longer creates/migrates tables itself at startup.
app = FastAPI(
    title="SumPoint",
    description="Intelligent Telegram content processing — AI digest, classification & event extraction",
    version="1.0.0",
)

_settings = get_settings()
_allowed_origins = [o.strip() for o in _settings.cors_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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
