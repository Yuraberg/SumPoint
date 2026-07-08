"""Celery task: evaluate user-defined cron schedules and fire the due ones."""
import logging

from croniter import croniter

from app.database import AsyncSessionLocal
from app.repositories import schedule_repository
from app.services.calendar_service import get_upcoming_events
from app.services.digest_delivery import format_events_message, send_digest_for_user
from app.tasks.base import get_bot, run
from app.tasks.celery_app import celery_app
from app.utils.text import truncate
from app.utils.time import utcnow

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.schedule_tasks.check_and_run_schedules")
def check_and_run_schedules():
    """Check all active user schedules and fire those that are due."""
    run(_async_check_schedules())


async def _async_check_schedules():
    now = utcnow()

    async with AsyncSessionLocal() as db:
        due = await schedule_repository.claim_due(db, now)

        for sched in due:
            try:
                next_run = croniter(sched.cron_expr, now).get_next(type(now))
            except Exception as e:
                logger.error(
                    "Invalid cron_expr for schedule %s (%s): %s — disabling",
                    sched.id, sched.name, e,
                )
                sched.status = "disabled"
                await db.commit()
                continue

            # Claim the next slot immediately so a concurrent worker won't
            # re-fire this row even if execution below takes a while.
            sched.next_run_at = next_run
            await db.commit()
            try:
                await _execute_schedule(db, sched)
                sched.last_run_at = now
            except Exception as e:
                logger.error("Schedule %s (%s) failed: %s", sched.id, sched.name, e)
            await db.commit()


async def _execute_schedule(db, sched):
    async with get_bot() as bot:
        await _execute_schedule_with_bot(db, sched, bot)


async def _execute_schedule_with_bot(db, sched, bot):
    if sched.schedule_type == "topics":
        await send_digest_for_user(
            bot, sched.user_id, db, sched.hours_back, sched.categories, sched.model
        )
    elif sched.schedule_type == "events":
        events = await get_upcoming_events(db, sched.user_id, days_ahead=7)
        text = format_events_message(events)
        await bot.send_message(
            chat_id=sched.user_id, text=truncate(text), parse_mode="Markdown"
        )
    elif sched.schedule_type == "collect":
        from app.tasks.fetch_tasks import fetch_all_channels
        fetch_all_channels.delay()
