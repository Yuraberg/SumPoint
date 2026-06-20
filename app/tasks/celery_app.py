from celery import Celery
from celery.schedules import crontab
from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "sumpoint",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
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
        # Once nightly — keeps Telethon polling (and the embedding pass it
        # triggers via process_post) off the 24/7 hot path.
        "schedule": crontab(hour=settings.posts_fetch_hour, minute=0),
    },
    "check-schedules": {
        "task": "app.tasks.digest_tasks.check_and_run_schedules",
        "schedule": 60.0,  # every minute
    },
}
