from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Telegram User API
    telegram_api_id: int = 0
    telegram_api_hash: str = ""

    # Telegram Bot
    telegram_bot_token: str = ""

    # Anthropic
    anthropic_api_key: str = ""

    # Database
    database_url: str = "postgresql+asyncpg://sumpoint:sumpoint@localhost:5432/sumpoint"

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # Security
    session_encryption_key: str = ""  # 32-byte hex
    secret_key: str = "change-me-in-production"

    # App
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = False

    # Digest schedule
    digest_morning_hour: int = 8
    digest_evening_hour: int = 20

    # Sessions directory
    sessions_dir: str = "sessions"


@lru_cache
def get_settings() -> Settings:
    return Settings()
