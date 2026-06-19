from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import get_settings

settings = get_settings()

_engine = None  # Lazy-init per event loop (avoids fork issues)


def _get_engine():
    global _engine
    url = settings.database_url
    if _engine is None:
        _engine = create_async_engine(url, echo=settings.debug)
    return _engine


def _dispose_engine():
    """Drop the engine reference without closing connections.
    Connections will be garbage-collected. This avoids loop-conflict
    errors when Celery forks worker processes.
    """
    global _engine
    _engine = None


def _get_sessionmaker():
    return async_sessionmaker(_get_engine(), expire_on_commit=False)


# Backward-compatible alias: callers use `AsyncSessionLocal()` as before
def AsyncSessionLocal():
    return _get_sessionmaker()()


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with _get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Create tables, enable pgvector, and migrate the embedding column to
    vector(1024) exactly once (idempotent — skipped if already migrated)."""
    import app.models  # noqa: F401
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text(
            "ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS chat_id BIGINT"
        ))

        result = await conn.execute(text(
            "SELECT atttypmod FROM pg_attribute a "
            "JOIN pg_class c ON a.attrelid = c.oid "
            "WHERE c.relname = 'posts' AND a.attname = 'embedding' AND a.attnum > 0"
        ))
        row = result.first()
        # atttypmod for vector(1024) is 1024; absent table or wrong dim -> migrate.
        if row is not None and row[0] != 1024:
            await conn.execute(text("ALTER TABLE posts ALTER COLUMN embedding DROP DEFAULT"))
            await conn.execute(text("UPDATE posts SET embedding = NULL"))
            await conn.execute(text("ALTER TABLE posts ALTER COLUMN embedding TYPE vector(1024)"))
            await conn.execute(text(
                "ALTER TABLE posts ALTER COLUMN embedding SET DEFAULT array_fill(0::real, ARRAY[1024])::vector"
            ))

        await conn.run_sync(Base.metadata.create_all)
