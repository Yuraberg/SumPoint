from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

from app.constants import DEFAULT_MODEL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Telegram User API
    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telegram_session_string: str = ""

    # Telegram Bot
    telegram_bot_token: str = ""

    # DeepSeek
    deepseek_api_key: str = ""
    deepseek_model: str = DEFAULT_MODEL
    deepseek_base_url: str = "https://api.deepseek.com"

    # Ollama (embeddings)
    ollama_base_url: str = "http://172.20.0.1:11434"

    # Database
    database_url: str = "postgresql+asyncpg://sumpoint:sumpoint@localhost:5432/sumpoint"

    # Redis — also used as the Celery broker/result backend (see app/tasks/celery_app.py)
    redis_url: str = "redis://localhost:6379/0"

    # Uptime Kuma push-monitor URL. If set, a periodic Celery task pings it
    # so Uptime Kuma can alert when the worker/beat stop ticking.
    uptime_kuma_push_url: str = ""

    # Auth secrets
    secret_key: str
    session_encryption_key: str = ""

    # CORS — JSON array of allowed origins, e.g. ["https://sum.procpoint.ru"]
    cors_origins: list[str] = ["http://localhost:8000", "http://localhost:8001"]

    # Public app URL (used in magic-link / mini-app links) and bot username
    app_base_url: str = "http://localhost:8001"
    telegram_bot_username: str = "SumProcPointBot"

    # Digest schedule
    digest_morning_hour: int = 8
    digest_evening_hour: int = 20

    # Continuous channel-fetch pacing — runs every N minutes, processing a small
    # slice of channels each time (oldest last_fetched_at first) so Telethon
    # polling stays spread out instead of bursting and risking a flood ban.
    posts_fetch_interval_minutes: int = 20
    posts_fetch_batch_size: int = 20

    # Debug
    debug: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
