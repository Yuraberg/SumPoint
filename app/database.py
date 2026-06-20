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

