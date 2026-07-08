"""Celery task: scheduled morning/evening digest delivery.

The channel-fetch, cron-schedule, and Telethon-maintenance tasks used to live
here too; they now have their own modules (fetch_tasks, schedule_tasks,
maintenance_tasks). Their public task objects are re-exported below so existing
``from app.tasks.digest_tasks import X`` call sites keep working.
"""
import logging

from app.database import AsyncSessionLocal
from app.repositories import schedule_repository, user_repository
from app.services.digest_delivery import send_digest_for_user
from app.tasks.base import get_bot, run
from app.tasks.celery_app import celery_app

# Backward-compatible re-exports (task objects registered in their own modules).
from app.tasks.fetch_tasks import fetch_all_channels  # noqa: F401
from app.tasks.maintenance_tasks import (  # noqa: F401
    import_channels_for_user,
    resolve_channel_username,
    uptime_kuma_heartbeat,
)
from app.tasks.schedule_tasks import check_and_run_schedules  # noqa: F401

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.digest_tasks.send_scheduled_digests",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=120,
    max_retries=3,
)
def send_scheduled_digests(slot: str):
    """Trigger digest delivery for all users who opted in to this slot."""
    run(_async_send_digests(slot))


async def _async_send_digests(slot: str):
    async with get_bot() as bot, AsyncSessionLocal() as db:
        users = await user_repository.get_digest_subscribers(db, slot)

        for user in users:
            try:
                sched = await schedule_repository.get_digest_slot(
                    db, user.id, slot, enabled_only=True
                )
                hours = sched.hours_back if sched else 24
                categories = sched.categories if (sched and sched.categories) else None
                model = sched.model if sched else None
                await send_digest_for_user(bot, user.id, db, hours, categories, model)
            except Exception as e:
                logger.error("Failed to send digest to user %s: %s", user.id, e)
