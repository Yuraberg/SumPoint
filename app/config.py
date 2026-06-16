from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


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

    # Ollama (embeddings)
    ollama_base_url: str = "http://172.20.0.1:11434"

    # Database
    database_url: str = "postgresql+asyncpg://sumpoint:sumpoint@localhost:5432/sumpoint"

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"

    # Celery
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/0"

    # Auth secrets
    secret_key: str = ""
    session_encryption_key: str = ""

    # Digest schedule
    digest_morning_hour: int = 8
    digest_evening_hour: int = 20

    # Debug
    debug: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
