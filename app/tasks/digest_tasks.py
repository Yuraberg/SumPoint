"""Celery tasks for digest scheduling and channel polling."""
import asyncio
import logging
from datetime import datetime

from app.tasks.celery_app import celery_app
from app.database import AsyncSessionLocal
from app.models.user import User
from app.models.channel import Channel
from app.models.post import Post
from app.services.telegram_ingestion import TelegramIngestion
from app.services.ai_engine import process_post
from sqlalchemy import select

logger = logging.getLogger(__name__)

# ── Anti-flood constants ───────────────────────────────────────────────────────
_CHANNEL_DELAY = 1.5    # seconds between individual channel fetches
_BATCH_SIZE = 5         # channels per batch before a longer pause
_BATCH_DELAY = 8.0      # seconds between batches


def _run(coro):
    """Run an async coroutine from a sync Celery task."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Monitoring: fetch new posts every 5 min ───────────────────────────────────

@celery_app.task(name="app.tasks.digest_tasks.fetch_all_channels")
def fetch_all_channels():
    """Fetch new posts from all active channels for all users."""
    _run(_async_fetch_all())


async def _async_fetch_all():
    from app.config import get_settings
    _settings = get_settings()
    async with AsyncSessionLocal() as db:
        users = (await db.execute(select(User).where(User.is_active == True))).scalars().all()   # noqa: E712
        for user in users:
            if not _settings.telegram_session_string and not user.session_path:
                continue
            channels = (
                await db.execute(
                    select(Channel).where(Channel.user_id == user.id, Channel.is_active == True)   # noqa: E712
                )
            ).scalars().all()
            if not channels:
                continue

            ingestion = TelegramIngestion(user.id, user.session_path or "")
            try:
                client = await ingestion._get_client()
                await client.get_dialogs()

                for i, channel in enumerate(channels):
                    try:
                        async for raw_post in ingestion.fetch_recent_posts(channel.telegram_id, hours=24):
                            if raw_post["is_ad"]:
                                continue
                            existing = (
                                await db.execute(
                                    select(Post).where(
                                        Post.channel_id == channel.id,
                                        Post.telegram_message_id == raw_post["telegram_message_id"],
                                    )
                                )
                            ).scalar_one_or_none()
                            if existing:
                                continue

                            enriched = process_post(raw_post["text"], channel.title)
                            pub_at = raw_post["published_at"]
                            if pub_at.tzinfo is not None:
                                pub_at = pub_at.replace(tzinfo=None)
                            post = Post(
                                channel_id=channel.id,
                                telegram_message_id=raw_post["telegram_message_id"],
                                text=raw_post["text"],
                                published_at=pub_at,
                                is_ad=raw_post["is_ad"],
                                category=enriched["category"],
                                summary=enriched["summary"],
                                events=enriched["events"] or None,
                                embedding=enriched["embedding"],
                                processed_at=datetime.utcnow(),
                            )
                            db.add(post)
                        channel.last_fetched_at = datetime.utcnow()
                        await db.commit()
                    except Exception as e:
                        logger.warning("Skipping channel %s (%s): %s", channel.title, channel.telegram_id, e)
                        await db.rollback()

                    # Anti-flood: pause between channels, longer pause between batches
                    if (i + 1) % _BATCH_SIZE == 0:
                        await asyncio.sleep(_BATCH_DELAY)
                    else:
                        await asyncio.sleep(_CHANNEL_DELAY)

            except Exception as e:
                logger.error("Error fetching for user %s: %s", user.id, e)
                await db.rollback()
            finally:
                await ingestion.disconnect()


# ── Scheduled digests (09:00 and 21:00 UTC) ──────────────────────────────────

@celery_app.task(name="app.tasks.digest_tasks.send_scheduled_digests")
def send_scheduled_digests(slot: str):
    """Trigger digest delivery for all users who opted in to this slot."""
    _run(_async_send_digests(slot))


async def _async_send_digests(slot: str):
    from app.services.digest_service import build_user_digest
    from app.models.digest_schedule import DigestSchedule
    from app.config import get_settings
    from telegram import Bot

    settings = get_settings()
    bot = Bot(token=settings.telegram_bot_token)

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

                digest = await build_user_digest(
                    db, user.id, hours=hours, categories=categories, model=model
                )
                text = digest.get("digest_markdown") or "Нет новых постов."
                if len(text) > 4000:
                    text = text[:4000] + "\n…"
                await bot.send_message(chat_id=user.id, text=text, parse_mode="Markdown")
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
            try:
                await _execute_schedule(db, sched)
                sched.last_run_at = now
            except Exception as e:
                logger.error("Schedule %s (%s) failed: %s", sched.id, sched.name, e)
            finally:
                sched.next_run_at = croniter(sched.cron_expr, now).get_next(datetime)

        if due:
            await db.commit()


async def _execute_schedule(db, sched):
    from app.config import get_settings
    from telegram import Bot
    settings = get_settings()
    bot = Bot(token=settings.telegram_bot_token)

    if sched.schedule_type == "topics":
        from app.services.digest_service import build_user_digest
        digest = await build_user_digest(
            db, sched.user_id,
            hours=sched.hours_back,
            categories=sched.categories,
            model=sched.model,
        )
        text = digest.get("digest_markdown") or "Нет новых постов."
        if len(text) > 4000:
            text = text[:4000] + "\n…"
        await bot.send_message(chat_id=sched.user_id, text=text, parse_mode="Markdown")

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
        await bot.send_message(chat_id=sched.user_id, text=text, parse_mode="Markdown")

    elif sched.schedule_type == "collect":
        fetch_all_channels.delay()


# ── Channel import / resolve (worker-only Telethon operations) ────────────────

@celery_app.task(name="app.tasks.digest_tasks.import_channels_for_user")
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
