from celery import Celery
from celery.schedules import crontab
from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "sumpoint",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.digest_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
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
        "task": "app.tasks.digest_tasks.fetch_all_channels",
        # Runs continuously but only processes a small slice of channels per
        # run (oldest last_fetched_at first) — keeps Telethon polling spread
        # out instead of bursting through everything at once.
        "schedule": settings.posts_fetch_interval_minutes * 60.0,
    },
    "check-schedules": {
        "task": "app.tasks.digest_tasks.check_and_run_schedules",
        "schedule": 60.0,  # every minute
    },
    "uptime-kuma-heartbeat": {
        "task": "app.tasks.digest_tasks.uptime_kuma_heartbeat",
        "schedule": 300.0,  # every 5 minutes
    },
}
