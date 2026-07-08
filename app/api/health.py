"""Health check endpoint — used by Uptime Kuma and Docker HEALTHCHECK."""
import logging

import redis.asyncio as aioredis
from fastapi import APIRouter
from sqlalchemy import text

from app.config import get_settings
from app.database import AsyncSessionLocal

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """Deep health check: verifies DB and Redis connectivity.

    Returns 200 with per-component status if everything is healthy.
    Returns 503 if any critical dependency is unreachable.

    Use this in Uptime Kuma (HTTP monitor) — it'll alert if DB or Redis go down.
    """
    settings = get_settings()
    status = {"database": "unknown", "redis": "unknown"}

    # ── Database check ────────────────────────────────────────────────
    try:
        session = AsyncSessionLocal()
        await session.execute(text("SELECT 1"))
        await session.close()
        status["database"] = "ok"
    except Exception as exc:
        status["database"] = f"error: {exc}"
        logger.error("Health check: database unreachable — %s", exc)

    # ── Redis check ───────────────────────────────────────────────────
    try:
        r = aioredis.from_url(settings.redis_url)
        await r.ping()
        await r.aclose()
        status["redis"] = "ok"
    except Exception as exc:
        status["redis"] = f"error: {exc}"
        logger.error("Health check: redis unreachable — %s", exc)

    # ── Determine overall health ──────────────────────────────────────
    all_ok = all(v == "ok" for v in status.values())
    return {
        "status": "healthy" if all_ok else "degraded",
        "checks": status,
    }
