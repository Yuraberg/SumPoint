"""Celery tasks for polling channels and ingesting new posts."""
import asyncio
import logging

from sqlalchemy.exc import IntegrityError

from app.tasks.celery_app import celery_app
from app.tasks.base import run, get_bot
from app.config import get_settings
from app.constants import (
    CHANNEL_FETCH_DELAY,
    CHANNEL_BATCH_SIZE,
    CHANNEL_BATCH_DELAY,
    CONTENT_DEDUP_WINDOW_DAYS,
    FETCH_HISTORY_HOURS,
    FETCH_LOCK_KEY,
    FETCH_LOCK_TTL,
)
from app.database import AsyncSessionLocal
from app.models.post import Post
from app.models.channel import Channel
from app.models.user import User
from app.repositories import channel_repository, post_repository, user_repository
from app.repositories import alert_repository
from app.services.telegram_ingestion import TelegramIngestion
from app.services.ai_engine import process_post
from app.utils.time import utcnow

from datetime import timedelta

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.fetch_tasks.fetch_all_channels",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=3,
)
def fetch_all_channels():
    """Fetch new posts from all active channels for all users."""
    run(_async_fetch_all())


async def _try_acquire_fetch_lock():
    """Redis NX lock so an overlapping manual /channels/sync (or a second beat
    tick) can't run fetch_all_channels concurrently — concurrent runs raced on
    the same dedup checks and produced duplicate inserts / lost-update
    rollbacks on shared channels. Returns the connection (holding the lock) or
    None if another run already holds it."""
    import redis.asyncio as aioredis

    r = aioredis.from_url(get_settings().redis_url)
    got_lock = await r.set(FETCH_LOCK_KEY, "1", nx=True, ex=FETCH_LOCK_TTL)
    if not got_lock:
        await r.aclose()
        return None
    return r


async def _async_fetch_all():
    settings = get_settings()

    lock = await _try_acquire_fetch_lock()
    if lock is None:
        logger.info("fetch_all_channels already running; skipping this tick")
        return

    try:
        async with AsyncSessionLocal() as db:
            rows = await channel_repository.get_fetch_batch(
                db,
                settings.posts_fetch_batch_size,
                require_session_path=not settings.telegram_session_string,
            )
            if not rows:
                return

            by_user: dict[int, list[Channel]] = {}
            users_by_id: dict[int, User] = {}
            for channel, user in rows:
                by_user.setdefault(user.id, []).append(channel)
                users_by_id[user.id] = user

            channel_index = 0
            for user_id, channels in by_user.items():
                user = users_by_id[user_id]
                channel_index = await _fetch_user_channels(db, user, channels, channel_index)
    finally:
        await lock.delete(FETCH_LOCK_KEY)
        await lock.aclose()


async def _fetch_user_channels(
    db, user: User, channels: list[Channel], channel_index: int
) -> int:
    """Fetch every channel for one user, pacing between calls. Returns the
    running channel counter so batch pauses stay global across users."""
    ingestion = TelegramIngestion(user.id, user.session_path or "")
    try:
        await ingestion.connect()

        for channel in channels:
            was_healthy = channel.last_error is None
            try:
                await _fetch_channel(db, ingestion, channel)
                channel_repository.mark_fetched(channel, utcnow())
                await db.commit()
            except Exception as e:
                logger.warning(
                    "Skipping channel %s (%s): %s",
                    channel.title, channel.telegram_id, str(e)[:200],
                )
                await _safe_rollback(db)
                channel_repository.mark_fetched(channel, utcnow(), error=str(e))
                await _safe_commit(db)
                if was_healthy and user.chat_id:
                    await _notify_channel_failure(user, channel, e)

            channel_index += 1
            if channel_index % CHANNEL_BATCH_SIZE == 0:
                await asyncio.sleep(CHANNEL_BATCH_DELAY)
            else:
                await asyncio.sleep(CHANNEL_FETCH_DELAY)
    except Exception as e:
        logger.error("Error fetching for user %s: %s", user.id, str(e)[:200])
        await _safe_rollback(db)
    finally:
        await ingestion.disconnect()
    return channel_index


async def _fetch_channel(db, ingestion: TelegramIngestion, channel: Channel) -> None:
    dedup_cutoff = utcnow() - timedelta(days=CONTENT_DEDUP_WINDOW_DAYS)

    async for raw_post in ingestion.fetch_recent_posts(
        channel.telegram_id, hours=FETCH_HISTORY_HOURS
    ):
        if raw_post["is_ad"]:
            continue

        if await post_repository.exists_by_message_id(
            db, channel.id, raw_post["telegram_message_id"]
        ):
            continue
        # Catches reposts of identical text under a different message id, which
        # the message-id uniqueness check above can't see.
        if await post_repository.exists_by_content_hash(
            db, channel.id, raw_post["content_hash"], dedup_cutoff
        ):
            continue

        enriched = await process_post(raw_post["text"], channel.title)
        if enriched is None:
            logger.warning(
                "AI processing failed for message %s in channel %s; skipping",
                raw_post["telegram_message_id"], channel.title,
            )
            continue

        pub_at = raw_post["published_at"]
        if pub_at.tzinfo is not None:
            pub_at = pub_at.replace(tzinfo=None)
        post = Post(
            channel_id=channel.id,
            telegram_message_id=raw_post["telegram_message_id"],
            content_hash=raw_post["content_hash"],
            text=raw_post["text"],
            published_at=pub_at,
            is_ad=raw_post["is_ad"],
            category=enriched["category"],
            summary=enriched["summary"],
            events=enriched["events"] or None,
            embedding=enriched["embedding"],
            processed_at=utcnow(),
        )
        # A savepoint per post so a duplicate raced in by a concurrent writer
        # (unique constraint violation) only discards this one insert instead of
        # rolling back every post already processed for this channel.
        try:
            async with db.begin_nested():
                db.add(post)
                await db.flush()
        except IntegrityError:
            logger.info(
                "Duplicate post %s in channel %s skipped (race with another run)",
                raw_post["telegram_message_id"], channel.title,
            )
            continue

        await _notify_keyword_alerts(db, channel, post)


async def _notify_keyword_alerts(db, channel: Channel, post: Post) -> None:
    """Notify the channel owner if a keyword alert matches the new post."""
    alerts = await alert_repository.list_for_user(db, channel.user_id)
    if not alerts:
        return

    haystack = f"{post.text or ''} {post.summary or ''}".lower()
    matched = [a.keyword for a in alerts if a.keyword in haystack]
    if not matched:
        return

    user = await user_repository.get_by_id(db, channel.user_id)
    if not user or not user.chat_id:
        return

    body = (post.summary or post.text or "")[:300]
    try:
        async with get_bot() as bot:
            await bot.send_message(
                chat_id=user.chat_id,
                text=f"🔔 «{channel.title}»: новый пост по словам {', '.join(matched)}\n\n{body}",
            )
    except Exception:
        logger.warning("Failed to send keyword alert notification to user %s", user.id)


async def _notify_channel_failure(user: User, channel: Channel, error: Exception) -> None:
    try:
        async with get_bot() as bot:
            await bot.send_message(
                chat_id=user.chat_id,
                text=f"⚠️ Канал «{channel.title}» перестал обновляться: {str(error)[:200]}",
            )
    except Exception:
        logger.warning(
            "Failed to notify user %s about channel %s failure", user.id, channel.id
        )


async def _safe_rollback(db) -> None:
    try:
        await db.rollback()
    except Exception:
        pass


async def _safe_commit(db) -> None:
    try:
        await db.commit()
    except Exception:
        pass
