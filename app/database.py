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
    global _engine
    if _engine is not None:
        _engine.sync_engine.dispose()
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
    """Create tables and enable pgvector extension."""
    import app.models  # noqa: F401
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.execute(__import__("sqlalchemy").text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(__import__("sqlalchemy").text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS chat_id BIGINT"
        ))
        await conn.execute(__import__("sqlalchemy").text(
            "ALTER TABLE posts ALTER COLUMN embedding DROP DEFAULT"
        ))
        await conn.execute(__import__("sqlalchemy").text(
            "UPDATE posts SET embedding = NULL"
        ))
        await conn.execute(__import__("sqlalchemy").text(
            "ALTER TABLE posts ALTER COLUMN embedding TYPE vector(1024)"
        ))
        await conn.execute(__import__("sqlalchemy").text(
            "ALTER TABLE posts ALTER COLUMN embedding SET DEFAULT array_fill(0::real, ARRAY[1024])::vector"
        ))
        await conn.run_sync(Base.metadata.create_all)
