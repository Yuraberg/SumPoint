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


def _run(coro):
    """Run an async coroutine from a sync Celery task."""
    return asyncio.get_event_loop().run_until_complete(coro)


@celery_app.task(name="app.tasks.digest_tasks.fetch_all_channels")
def fetch_all_channels():
    """Fetch new posts from all active channels for all users."""
    _run(_async_fetch_all())


async def _async_fetch_all():
    async with AsyncSessionLocal() as db:
        users = (await db.execute(select(User).where(User.is_active == True))).scalars().all()   # noqa: E712
        for user in users:
            if not user.session_path:
                continue
            channels = (
                await db.execute(
                    select(Channel).where(Channel.user_id == user.id, Channel.is_active == True)   # noqa: E712
                )
            ).scalars().all()
            if not channels:
                continue

            ingestion = TelegramIngestion(user.id, user.session_path)
            try:
                for channel in channels:
                    async for raw_post in ingestion.fetch_recent_posts(channel.telegram_id, hours=1):
                        # Skip ads
                        if raw_post["is_ad"]:
                            continue
                        # Skip if already stored
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

                        # AI processing
                        enriched = process_post(raw_post["text"], channel.title)
                        post = Post(
                            channel_id=channel.id,
                            telegram_message_id=raw_post["telegram_message_id"],
                            text=raw_post["text"],
                            published_at=raw_post["published_at"],
                            is_ad=raw_post["is_ad"],
                            category=enriched["category"],
                            summary=enriched["summary"],
                            events=enriched["events"] or None,
                            embedding=enriched["embedding"],
                            processed_at=datetime.utcnow(),
                        )
                        db.add(post)
                        # Update channel last_fetched_at
                        channel.last_fetched_at = datetime.utcnow()

                await db.commit()
            except Exception as e:
                logger.error("Error fetching for user %s: %s", user.id, e)
                await db.rollback()
            finally:
                await ingestion.disconnect()


@celery_app.task(name="app.tasks.digest_tasks.send_scheduled_digests")
def send_scheduled_digests(slot: str):
    """
    Trigger digest delivery for all users who opted in to this slot.
    `slot` is 'morning' or 'evening'.
    """
    _run(_async_send_digests(slot))


async def _async_send_digests(slot: str):
    from app.services.digest_service import build_user_digest
    from app.config import get_settings
    from telegram import Bot

    settings = get_settings()
    bot = Bot(token=settings.telegram_bot_token)

    async with AsyncSessionLocal() as db:
        field = User.digest_morning if slot == "morning" else User.digest_evening
        users = (await db.execute(select(User).where(field == True))).scalars().all()   # noqa: E712

        for user in users:
            try:
                digest = await build_user_digest(db, user.id)
                text = digest.get("digest_markdown") or "No new posts today."
                await bot.send_message(chat_id=user.id, text=text, parse_mode="Markdown")
            except Exception as e:
                logger.error("Failed to send digest to user %s: %s", user.id, e)
