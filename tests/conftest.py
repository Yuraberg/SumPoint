"""Sets required env vars before any `app.*` module is imported, since
`app.config.Settings` requires SECRET_KEY with no default and several
services (encryption, auth) cache settings at import time."""
import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("SESSION_ENCRYPTION_KEY", "00" * 32)
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:test-bot-token")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("DEEPSEEK_API_KEY", "test-deepseek-key")
