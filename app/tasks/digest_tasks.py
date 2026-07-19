"""Celery task: scheduled morning/evening digest delivery.

The channel-fetch, cron-schedule, and Telethon-maintenance tasks used to live
here too; they now have their own modules (fetch_tasks, schedule_tasks,
maintenance_tasks). Their public task objects are re-exported below so existing
``from app.tasks.digest_tasks import X`` call sites keep working.
"""
import logging

import sentry_sdk

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.repositories import schedule_repository, user_repository
from app.services.digest_delivery import UndeliverableChatError, send_digest_for_user
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
            except UndeliverableChatError as e:
                # Retrying (now or on the next scheduled run) would fail the
                # exact same way — the account was deleted, the bot was
                # blocked, or the chat otherwise no longer exists. Turn the
                # flags off so this stops recurring every single slot.
                logger.warning(
                    "Digest permanently undeliverable for user %s (%s) — disabling digest_morning/digest_evening",
                    user.id, e,
                )
                user.digest_morning = False
                user.digest_evening = False
                await db.commit()
                await _notify_owners_digest_disabled(bot, user.id, e)
            except Exception as e:
                # This except swallows the failure as far as Celery is concerned
                # (autoretry_for on the task never sees it), so nothing else
                # would otherwise learn a digest silently failed to send.
                logger.error("Failed to send digest to user %s: %s", user.id, e)
                sentry_sdk.capture_exception(e)
                await _notify_owners_digest_failure(bot, slot, user.id, e)


async def _notify_owners_digest_failure(bot, slot: str, user_id: int, error: Exception) -> None:
    """DM every configured owner when a scheduled digest fails to send.

    Delivery failures here are otherwise invisible: they're caught before
    Celery's autoretry sees them, and (even with Sentry now wired up in the
    worker) a caught exception isn't auto-captured without this explicit call.
    """
    owner_ids = get_settings().owner_telegram_id_set
    if not owner_ids:
        return
    text = (
        f"⚠️ Не удалось отправить {slot}-дайджест пользователю `{user_id}`: "
        f"{str(error)[:200]}"
    )
    for owner_id in owner_ids:
        try:
            await bot.send_message(chat_id=owner_id, text=text, parse_mode="Markdown")
        except Exception:
            logger.warning("Failed to notify owner %s about digest failure", owner_id)


async def _notify_owners_digest_disabled(bot, user_id: int, error: Exception) -> None:
    """DM every configured owner once, when a user's digest is auto-disabled
    because their chat became permanently unreachable — a one-time notice
    instead of the same failure repeating every slot forever."""
    owner_ids = get_settings().owner_telegram_id_set
    if not owner_ids:
        return
    text = (
        f"🔕 Дайджест пользователю `{user_id}` отключён — чат недоступен "
        f"(аккаунт удалён или бот заблокирован): {str(error)[:200]}"
    )
    for owner_id in owner_ids:
        try:
            await bot.send_message(chat_id=owner_id, text=text, parse_mode="Markdown")
        except Exception:
            logger.warning("Failed to notify owner %s about digest auto-disable", owner_id)
