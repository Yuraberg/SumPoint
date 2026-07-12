"""Health check endpoints — used by Uptime Kuma and Docker HEALTHCHECK."""
import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, Response
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.channel import Channel
from app.utils.time import utcnow

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


@router.get("/health/fetch")
async def fetch_health_check(response: Response):
    """Checks whether the Celery beat/worker fetch pipeline is still alive.

    `fetch_all_channels` touches every channel's `last_fetched_at` once per
    tick — on both success and failure (see fetch_tasks.py). So the newest
    `last_fetched_at` across all channels is a liveness signal for the whole
    pipeline, independent of whether any channel actually had new posts.

    Stale beyond 2x the fetch interval means beat stopped scheduling ticks or
    the worker stopped picking them up — this is what caught the 2026-07-04
    to 2026-07-08 outage after a Docker restart left the worker wedged with no
    posts ingested for four days.

    Point a separate Uptime Kuma HTTP monitor at this endpoint.
    """
    settings = get_settings()
    threshold_minutes = 2 * settings.posts_fetch_interval_minutes

    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(func.max(Channel.last_fetched_at)))
            last_fetched_at = result.scalar_one_or_none()
    except SQLAlchemyError as exc:
        logger.error("Fetch health check: database unreachable — %s", exc)
        response.status_code = 503
        return {"status": "error", "detail": "database unreachable"}

    if last_fetched_at is None:
        response.status_code = 503
        return {"status": "error", "detail": "no channels have ever been fetched"}

    age_minutes = (utcnow() - last_fetched_at).total_seconds() / 60
    is_fresh = age_minutes <= threshold_minutes

    if not is_fresh:
        response.status_code = 503
    return {
        "status": "healthy" if is_fresh else "stale",
        "last_fetched_at": last_fetched_at.isoformat(),
        "age_minutes": round(age_minutes, 1),
        "threshold_minutes": threshold_minutes,
    }
