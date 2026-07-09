"""Worker-only Telethon operations (channel import / resolve) and monitoring."""
import logging

import httpx

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.channel import Channel
from app.repositories import channel_repository, user_repository
from app.services.telegram_ingestion import TelegramIngestion
from app.tasks.base import run
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.maintenance_tasks.import_channels_for_user",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    max_retries=2,
)
def import_channels_for_user(user_id: int) -> dict:
    """Import all subscribed Telegram channels for a user."""
    return run(_async_import_channels(user_id))


async def _async_import_channels(user_id: int) -> dict:
    async with AsyncSessionLocal() as db:
        user = await user_repository.get_by_id(db, user_id)
        if not user:
            return {"error": "User not found", "imported": 0, "total": 0}

        ingestion = TelegramIngestion(user_id, user.session_path or "")
        try:
            subscribed = await ingestion.get_subscribed_channels()
        except Exception as e:
            return {"error": str(e), "imported": 0, "total": 0}
        finally:
            await ingestion.disconnect()

        added = 0
        for ch_data in subscribed:
            existing = await channel_repository.get_by_telegram_id(
                db, user_id, ch_data["telegram_id"]
            )
            if existing:
                continue
            db.add(
                Channel(
                    user_id=user_id,
                    telegram_id=ch_data["telegram_id"],
                    username=ch_data.get("username"),
                    title=ch_data.get("title")
                    or ch_data.get("username")
                    or str(ch_data["telegram_id"]),
                )
            )
            added += 1

        await db.commit()
        return {"imported": added, "total": len(subscribed)}


@celery_app.task(name="app.tasks.maintenance_tasks.resolve_channel_username")
def resolve_channel_username(user_id: int, username: str) -> dict | None:
    """Resolve a Telegram @username to {telegram_id, title, username}."""
    return run(_async_resolve_username(user_id, username))


async def _async_resolve_username(user_id: int, username: str) -> dict | None:
    async with AsyncSessionLocal() as db:
        user = await user_repository.get_by_id(db, user_id)
    if not user:
        return None

    ingestion = TelegramIngestion(user_id, user.session_path or "")
    try:
        client = await ingestion._get_client()
        entity = await client.get_entity(username)
        return {
            "telegram_id": entity.id,
            "title": getattr(entity, "title", username),
            "username": getattr(entity, "username", None),
        }
    except Exception as e:
        raise RuntimeError(str(e))
    finally:
        await ingestion.disconnect()


@celery_app.task(name="app.tasks.maintenance_tasks.uptime_kuma_heartbeat")
def uptime_kuma_heartbeat():
    """Ping the configured Uptime Kuma push monitor so it can alert when the
    worker/beat stop ticking. No-op if UPTIME_KUMA_PUSH_URL isn't set."""
    url = get_settings().uptime_kuma_push_url
    if not url:
        return
    try:
        httpx.get(url, timeout=10)
    except Exception as e:
        logger.warning("Uptime Kuma heartbeat failed: %s", e)


@celery_app.task(name="app.tasks.maintenance_tasks.backfill_clusters")
def backfill_clusters(reset: bool = False) -> dict:
    """One-off (re)assignment of duplicate-cluster ids over existing posts.

    Run once after deploying the clustering feature so historical posts get
    grouped (new posts are clustered at ingestion). Pass reset=True to clear
    and recompute every cluster_id, e.g. after changing the similarity
    threshold. Safe to re-run: without reset it only touches unclustered posts.
    """
    return run(_async_backfill_clusters(reset))


async def _async_backfill_clusters(reset: bool) -> dict:
    from sqlalchemy import select, text

    from app.models.post import Post
    from app.models.user import User
    from app.services.clustering import assign_cluster

    async with AsyncSessionLocal() as db:
        if reset:
            await db.execute(text("UPDATE posts SET cluster_id = NULL"))
            await db.commit()

        user_ids = (await db.execute(select(User.id))).scalars().all()
        total = 0
        for uid in user_ids:
            # Oldest first so each post can attach to already-clustered earlier
            # ones; the per-post flush inside assign_cluster makes them visible.
            q = (
                select(Post)
                .join(Channel, Post.channel_id == Channel.id)
                .where(Channel.user_id == uid)
                .where(Post.cluster_id.is_(None))
                .where(Post.is_ad.is_(False))
                .order_by(Post.published_at.asc())
            )
            posts = (await db.execute(q)).scalars().all()
            for post in posts:
                await assign_cluster(db, post, uid, flush=True)
                total += 1
            await db.commit()
        logger.info("backfill_clusters done: %d posts clustered", total)
        return {"clustered": total, "users": len(user_ids)}
