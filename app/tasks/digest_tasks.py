"""Celery tasks for digest scheduling and channel polling."""
import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.tasks.celery_app import celery_app
from app.database import _dispose_engine, AsyncSessionLocal
from app.models.user import User
from app.models.channel import Channel
from app.models.post import Post
from app.models.keyword_alert import KeywordAlert
from app.services.telegram_ingestion import TelegramIngestion
from app.services.ai_engine import process_post

logger = logging.getLogger(__name__)

# ── Anti-flood constants ───────────────────────────────────────────────────────
_CHANNEL_DELAY = 1.5    # seconds between individual channel fetches
_BATCH_SIZE = 5         # channels per batch before a longer pause
_BATCH_DELAY = 8.0      # seconds between batches

# Reposted/identical text is deduped against posts published within this
# window, so a channel re-posting old content doesn't get flagged forever.
_CONTENT_DEDUP_WINDOW_DAYS = 14

_FETCH_LOCK_KEY = "sumpoint:fetch_lock"
_FETCH_LOCK_TTL = 600  # safety net if a worker dies mid-run, in seconds

_DIGEST_TEXT_LIMIT = 4000


def _truncate_digest(text: str) -> str:
    if len(text) > _DIGEST_TEXT_LIMIT:
        return text[:_DIGEST_TEXT_LIMIT] + "\n…"
    return text


async def _send_digest_for_user(bot, user_id: int, db, hours: int, categories, model: str | None) -> None:
    from app.services.digest_service import build_user_digest
    digest = await build_user_digest(db, user_id, hours=hours, categories=categories, model=model)
    text = _truncate_digest(digest.get("digest_markdown") or "Нет новых постов.")
    await bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")


def _get_bot():
    from app.config import get_settings
    from telegram import Bot
    return Bot(token=get_settings().telegram_bot_token)


def _run(coro):
    """Run an async coroutine from a sync Celery task.

    asyncio.run() creates a fresh event loop, executes the coroutine, then
    runs all remaining callbacks (asyncpg connection-close finalizers) before
    tearing the loop down. This prevents the MissingGreenlet error that
    await_fallback() produced because it left asyncpg cleanup callbacks
    scheduled after its greenlet context had already exited.
    """
    _dispose_engine()
    return asyncio.run(coro)


# ── Monitoring: fetch new posts every 5 min ───────────────────────────────────

@celery_app.task(
    name="app.tasks.digest_tasks.fetch_all_channels",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=3,
)
def fetch_all_channels():
    """Fetch new posts from all active channels for all users."""
    _run(_async_fetch_all())


async def _try_acquire_fetch_lock() -> "object | None":
    """Redis NX lock so an overlapping manual /channels/sync (or a second
    beat tick) can't run fetch_all_channels concurrently with this one —
    concurrent runs raced on the same dedup checks and produced duplicate
    inserts / lost-update rollbacks on shared channels."""
    import redis.asyncio as aioredis
    from app.config import get_settings

    r = aioredis.from_url(get_settings().redis_url)
    got_lock = await r.set(_FETCH_LOCK_KEY, "1", nx=True, ex=_FETCH_LOCK_TTL)
    if not got_lock:
        await r.aclose()
        return None
    return r


async def _async_fetch_all():
    from app.config import get_settings
    _settings = get_settings()

    lock = await _try_acquire_fetch_lock()
    if lock is None:
        logger.info("fetch_all_channels already running; skipping this tick")
        return

    try:
        async with AsyncSessionLocal() as db:
            stmt = (
                select(Channel, User)
                .join(User, Channel.user_id == User.id)
                .where(Channel.is_active == True, User.is_active == True)   # noqa: E712
            )
            if not _settings.telegram_session_string:
                stmt = stmt.where(User.session_path != None)   # noqa: E711
            # Oldest last_fetched_at first, then a bounded slice — spreads
            # Telethon traffic across runs instead of bursting through every
            # channel every time.
            stmt = stmt.order_by(Channel.last_fetched_at.asc().nulls_first()).limit(
                _settings.posts_fetch_batch_size
            )
            rows = (await db.execute(stmt)).all()
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
                ingestion = TelegramIngestion(user.id, user.session_path or "")
                try:
                    client = await ingestion._get_client()
                    await client.get_dialogs()

                    for channel in channels:
                        was_healthy = channel.last_error is None
                        try:
                            await _fetch_channel(db, ingestion, channel)
                            channel.last_fetched_at = datetime.utcnow()
                            channel.last_error = None
                            await db.commit()
                        except Exception as e:
                            logger.warning("Skipping channel %s (%s): %s", channel.title, channel.telegram_id, str(e)[:200])
                            try:
                                await db.rollback()
                            except Exception:
                                pass
                            channel.last_error = str(e)[:1000]
                            channel.last_fetched_at = datetime.utcnow()
                            try:
                                await db.commit()
                            except Exception:
                                pass

                            if was_healthy and user.chat_id:
                                try:
                                    bot = _get_bot()
                                    await bot.send_message(
                                        chat_id=user.chat_id,
                                        text=f"⚠️ Канал «{channel.title}» перестал обновляться: {str(e)[:200]}",
                                    )
                                except Exception:
                                    logger.warning("Failed to notify user %s about channel %s failure", user.id, channel.id)

                        # Anti-flood: pause between channels, longer pause between batches
                        channel_index += 1
                        if channel_index % _BATCH_SIZE == 0:
                            await asyncio.sleep(_BATCH_DELAY)
                        else:
                            await asyncio.sleep(_CHANNEL_DELAY)

                except Exception as e:
                    logger.error("Error fetching for user %s: %s", user.id, str(e)[:200])
                    try:
                        await db.rollback()
                    except Exception:
                        pass
                finally:
                    await ingestion.disconnect()
    finally:
        await lock.delete(_FETCH_LOCK_KEY)
        await lock.aclose()


async def _fetch_channel(db, ingestion: TelegramIngestion, channel: Channel) -> None:
    dedup_cutoff = datetime.utcnow() - timedelta(days=_CONTENT_DEDUP_WINDOW_DAYS)

    async for raw_post in ingestion.fetch_recent_posts(channel.telegram_id, hours=24):
        if raw_post["is_ad"]:
            continue

        existing = (
            await db.execute(
                select(Post.id).where(
                    Post.channel_id == channel.id,
                    Post.telegram_message_id == raw_post["telegram_message_id"],
                )
            )
        ).scalar_one_or_none()
        if existing:
            continue

        # Catches reposts of identical text under a different message id,
        # which the message-id uniqueness check above can't see.
        dup_content = (
            await db.execute(
                select(Post.id).where(
                    Post.channel_id == channel.id,
                    Post.content_hash == raw_post["content_hash"],
                    Post.published_at >= dedup_cutoff,
                )
            )
        ).scalar_one_or_none()
        if dup_content:
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
            processed_at=datetime.utcnow(),
        )
        # A savepoint per post so a duplicate raced in by a concurrent writer
        # (unique constraint violation) only discards this one insert instead
        # of rolling back every post already processed for this channel.
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
    alerts = (
        await db.execute(select(KeywordAlert).where(KeywordAlert.user_id == channel.user_id))
    ).scalars().all()
    if not alerts:
        return

    haystack = f"{post.text or ''} {post.summary or ''}".lower()
    matched = [a.keyword for a in alerts if a.keyword in haystack]
    if not matched:
        return

    user = (await db.execute(select(User).where(User.id == channel.user_id))).scalar_one_or_none()
    if not user or not user.chat_id:
        return

    try:
        bot = _get_bot()
        await bot.send_message(
            chat_id=user.chat_id,
            text=f"🔔 «{channel.title}»: новый пост по словам {', '.join(matched)}\n\n{(post.summary or post.text or '')[:300]}",
        )
    except Exception:
        logger.warning("Failed to send keyword alert notification to user %s", user.id)


# ── Scheduled digests (09:00 and 21:00 UTC) ──────────────────────────────────

@celery_app.task(
    name="app.tasks.digest_tasks.send_scheduled_digests",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=120,
    max_retries=3,
)
def send_scheduled_digests(slot: str):
    """Trigger digest delivery for all users who opted in to this slot."""
    _run(_async_send_digests(slot))


async def _async_send_digests(slot: str):
    from app.models.digest_schedule import DigestSchedule

    bot = _get_bot()

    async with AsyncSessionLocal() as db:
        field = User.digest_morning if slot == "morning" else User.digest_evening
        users = (await db.execute(select(User).where(field == True))).scalars().all()   # noqa: E712

        for user in users:
            try:
                # Load per-user schedule preferences for this slot
                sched = (
                    await db.execute(
                        select(DigestSchedule).where(
                            DigestSchedule.user_id == user.id,
                            DigestSchedule.slot == slot,
                            DigestSchedule.enabled == True,   # noqa: E712
                        )
                    )
                ).scalar_one_or_none()

                hours = sched.hours_back if sched else 24
                categories = sched.categories if (sched and sched.categories) else None
                model = sched.model if sched else None

                await _send_digest_for_user(bot, user.id, db, hours, categories, model)
            except Exception as e:
                logger.error("Failed to send digest to user %s: %s", user.id, e)


# ── Dynamic schedule runner (every minute) ────────────────────────────────────

@celery_app.task(name="app.tasks.digest_tasks.check_and_run_schedules")
def check_and_run_schedules():
    """Check all active user schedules and fire those that are due."""
    _run(_async_check_schedules())


async def _async_check_schedules():
    from croniter import croniter
    from app.models.schedule import Schedule
    from sqlalchemy import or_

    now = datetime.utcnow()

    async with AsyncSessionLocal() as db:
        due = (
            await db.execute(
                select(Schedule).where(
                    Schedule.status == "active",
                    or_(Schedule.next_run_at <= now, Schedule.next_run_at == None),   # noqa: E711
                )
            )
        ).scalars().all()

        for sched in due:
            # Claim the schedule immediately so a concurrent worker picking up
            # the same due row won't also execute and double-send it.
            sched.next_run_at = croniter(sched.cron_expr, now).get_next(datetime)
            await db.commit()
            try:
                await _execute_schedule(db, sched)
                sched.last_run_at = now
            except Exception as e:
                logger.error("Schedule %s (%s) failed: %s", sched.id, sched.name, e)
            await db.commit()


async def _execute_schedule(db, sched):
    bot = _get_bot()

    if sched.schedule_type == "topics":
        await _send_digest_for_user(
            bot, sched.user_id, db, sched.hours_back, sched.categories, sched.model
        )

    elif sched.schedule_type == "events":
        from app.services.calendar_service import get_upcoming_events
        events = await get_upcoming_events(db, sched.user_id, days_ahead=7)
        if events:
            lines = ["📅 *Предстоящие события:*\n"]
            for ev in events[:10]:
                name = ev.get("name") or "Событие"
                date = ev.get("date") or ""
                time_ = ev.get("time") or ""
                link = ev.get("link") or ""
                line = f"• *{name}* — {date} {time_}".strip()
                if link:
                    line += f" [→]({link})"
                lines.append(line)
            text = "\n".join(lines)
        else:
            text = "📅 Нет предстоящих событий на ближайшие 7 дней."
        await bot.send_message(chat_id=sched.user_id, text=_truncate_digest(text), parse_mode="Markdown")

    elif sched.schedule_type == "collect":
        fetch_all_channels.delay()


# ── Channel import / resolve (worker-only Telethon operations) ────────────────

@celery_app.task(
    name="app.tasks.digest_tasks.import_channels_for_user",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    max_retries=2,
)
def import_channels_for_user(user_id: int) -> dict:
    """Import all subscribed Telegram channels for a user."""
    return _run(_async_import_channels(user_id))


async def _async_import_channels(user_id: int) -> dict:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
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
            existing = (
                await db.execute(
                    select(Channel).where(
                        Channel.user_id == user_id,
                        Channel.telegram_id == ch_data["telegram_id"],
                    )
                )
            ).scalar_one_or_none()
            if existing:
                continue
            ch = Channel(
                user_id=user_id,
                telegram_id=ch_data["telegram_id"],
                username=ch_data.get("username"),
                title=ch_data.get("title") or ch_data.get("username") or str(ch_data["telegram_id"]),
            )
            db.add(ch)
            added += 1

        await db.commit()
        return {"imported": added, "total": len(subscribed)}


@celery_app.task(name="app.tasks.digest_tasks.uptime_kuma_heartbeat")
def uptime_kuma_heartbeat():
    """Ping the configured Uptime Kuma push monitor so it can alert when
    the worker/beat stop ticking. No-op if UPTIME_KUMA_PUSH_URL isn't set."""
    from app.config import get_settings
    import httpx

    url = get_settings().uptime_kuma_push_url
    if not url:
        return
    try:
        httpx.get(url, timeout=10)
    except Exception as e:
        logger.warning("Uptime Kuma heartbeat failed: %s", e)


@celery_app.task(name="app.tasks.digest_tasks.resolve_channel_username")
def resolve_channel_username(user_id: int, username: str) -> dict | None:
    """Resolve a Telegram @username to {telegram_id, title}."""
    return _run(_async_resolve_username(user_id, username))


async def _async_resolve_username(user_id: int, username: str) -> dict | None:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
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
