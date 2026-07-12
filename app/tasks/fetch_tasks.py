"""Celery tasks for polling channels and ingesting new posts."""
import asyncio
import contextlib
import logging
from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from telethon.errors import FloodWaitError

from app.config import get_settings
from app.constants import (
    AUTO_DEACTIVATE_AFTER_FAILURES,
    CHANNEL_BATCH_DELAY,
    CHANNEL_BATCH_SIZE,
    CHANNEL_FETCH_DELAY,
    CONTENT_DEDUP_WINDOW_DAYS,
    FETCH_HISTORY_HOURS,
    FETCH_LOCK_KEY,
    FETCH_LOCK_TTL,
)
from app.database import AsyncSessionLocal
from app.models.channel import Channel
from app.models.post import Post
from app.models.user import User
from app.repositories import (
    alert_repository,
    channel_repository,
    post_repository,
    user_repository,
)
from app.services.ai_engine import process_post
from app.services.clustering import assign_cluster
from app.services.telegram_ingestion import TelegramIngestion
from app.tasks.base import get_bot, run
from app.tasks.celery_app import celery_app
from app.utils.time import utcnow

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
    # Snapshot before any rollback can happen: db.rollback() expires every ORM
    # object in the session, and under an async session reading an expired
    # attribute afterward needs an implicit DB round-trip that can't happen
    # outside `await` — it raises MissingGreenlet and takes down the whole
    # tick (not just this channel/user) instead of just this iteration.
    user_id = user.id
    user_chat_id = user.chat_id

    ingestion = TelegramIngestion(user_id, user.session_path or "")
    try:
        await ingestion.connect()

        for channel in channels:
            was_healthy = channel.last_error is None
            prev_error_count = channel.error_count or 0
            channel_title = channel.title
            channel_telegram_id = channel.telegram_id
            channel_was_active = channel.is_active
            try:
                await _fetch_channel(db, ingestion, channel)
                channel_repository.mark_fetched(channel, utcnow())
                await db.commit()
            except FloodWaitError as e:
                # Flood waits are enforced per-session (this user's Telethon
                # client), not per-channel — trying the next channel would
                # just hit the same wait again and risks compounding into a
                # longer ban. Stop this user's channels for the tick instead
                # of looping through the rest; the next scheduled tick will
                # pick up where mark_fetched left off.
                logger.warning(
                    "Flood wait for user %s (%ss) on channel %s — stopping "
                    "this user's channels for this tick",
                    user_id, e.seconds, channel_title,
                )
                await _safe_rollback(db)
                channel_repository.mark_fetched(
                    channel, utcnow(), error=f"flood wait {e.seconds}s"
                )
                await _safe_commit(db)
                break
            except Exception as e:
                logger.warning(
                    "Skipping channel %s (%s): %s",
                    channel_title, channel_telegram_id, str(e)[:200],
                )
                await _safe_rollback(db)
                channel_repository.mark_fetched(
                    channel, utcnow(), error=str(e),
                    count_failure=True, prev_error_count=prev_error_count,
                )
                # Too many consecutive failures → a permanently-broken channel
                # (deleted/renamed, or a stale session). Deactivate so we stop
                # spending Telethon calls on it; the user can re-enable it later.
                new_error_count = prev_error_count + 1
                deactivated = False
                if new_error_count >= AUTO_DEACTIVATE_AFTER_FAILURES and channel_was_active:
                    channel.is_active = False
                    deactivated = True
                    logger.warning(
                        "Auto-deactivated channel %s (%s) after %d consecutive failures",
                        channel_title, channel_telegram_id, new_error_count,
                    )
                await _safe_commit(db)
                if user_chat_id and (deactivated or was_healthy):
                    await _notify_channel_failure(
                        user_id, user_chat_id, channel_title, e, deactivated=deactivated,
                        error_count=new_error_count,
                    )

            channel_index += 1
            if channel_index % CHANNEL_BATCH_SIZE == 0:
                await asyncio.sleep(CHANNEL_BATCH_DELAY)
            else:
                await asyncio.sleep(CHANNEL_FETCH_DELAY)
    except Exception as e:
        logger.error("Error fetching for user %s: %s", user_id, str(e)[:200])
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

        # Group near-duplicate reposts across channels. Isolated in its own
        # savepoint so a clustering hiccup never discards the stored post.
        try:
            async with db.begin_nested():
                await assign_cluster(db, post, channel.user_id)
        except Exception:
            logger.exception(
                "Cluster assignment failed for post %s in channel %s",
                post.id, channel.title,
            )

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


async def _notify_channel_failure(
    user_id: int,
    user_chat_id: int,
    channel_title: str,
    error: Exception,
    *,
    deactivated: bool = False,
    error_count: int = 0,
) -> None:
    if deactivated:
        text = (
            f"🚫 Канал «{channel_title}» отключён после {error_count} "
            f"неудачных попыток подряд: {str(error)[:160]}\n"
            "Проверьте, что канал существует и Telethon-сессия актуальна, "
            "затем включите его снова на странице «Каналы»."
        )
    else:
        text = f"⚠️ Канал «{channel_title}» перестал обновляться: {str(error)[:200]}"
    try:
        async with get_bot() as bot:
            await bot.send_message(chat_id=user_chat_id, text=text)
    except Exception:
        logger.warning(
            "Failed to notify user %s about channel %s failure", user_id, channel_title
        )


async def _safe_rollback(db) -> None:
    with contextlib.suppress(Exception):
        await db.rollback()


async def _safe_commit(db) -> None:
    with contextlib.suppress(Exception):
        await db.commit()
