import logging

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

# httpx (used directly and via python-telegram-bot's HTTPXRequest) logs each
# request at INFO with the full URL — and the Telegram Bot API embeds the bot
# token in the URL path (/bot<TOKEN>/method) — so leaving it at INFO leaks the
# token into worker/beat stdout on every digest/alert/notification send. The API
# process gets the same suppression in app/main.py; this module is the
# equivalent entrypoint for the worker and beat processes (neither imports
# app.main). Explicit per-logger levels aren't reset by Celery's own
# --loglevel=info setup, so this is safe regardless of import order.
# ("celery" itself is deliberately NOT included — --loglevel=info's
# task-received/task-succeeded logs are exactly what makes the worker
# observable, unlike in the api process where that logger is inert noise.)
if settings.log_level.upper() != "DEBUG":
    for _lib in ("httpx", "httpcore", "openai", "sqlalchemy.engine"):
        logging.getLogger(_lib).setLevel(logging.WARNING)

celery_app = Celery(
    "sumpoint",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.tasks.digest_tasks",
        "app.tasks.fetch_tasks",
        "app.tasks.schedule_tasks",
        "app.tasks.maintenance_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
)

celery_app.conf.beat_schedule = {
    "morning-digest": {
        "task": "app.tasks.digest_tasks.send_scheduled_digests",
        "schedule": crontab(hour=settings.digest_morning_hour, minute=0),
        "args": ["morning"],
    },
    "evening-digest": {
        "task": "app.tasks.digest_tasks.send_scheduled_digests",
        "schedule": crontab(hour=settings.digest_evening_hour, minute=0),
        "args": ["evening"],
    },
    "fetch-new-posts": {
        "task": "app.tasks.fetch_tasks.fetch_all_channels",
        # Runs continuously but only processes a small slice of channels per
        # run (oldest last_fetched_at first) — keeps Telethon polling spread
        # out instead of bursting through everything at once.
        "schedule": settings.posts_fetch_interval_minutes * 60.0,
    },
    "check-schedules": {
        "task": "app.tasks.schedule_tasks.check_and_run_schedules",
        "schedule": 60.0,  # every minute
    },
    "uptime-kuma-heartbeat": {
        "task": "app.tasks.maintenance_tasks.uptime_kuma_heartbeat",
        "schedule": 300.0,  # every 5 minutes
    },
}
