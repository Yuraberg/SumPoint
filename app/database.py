from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool
from app.config import get_settings

settings = get_settings()

_engine = None  # Lazy-init per event loop (avoids fork issues)


def _get_engine():
    global _engine
    url = settings.database_url
    if _engine is None:
        # NullPool: no pooled connections to close outside the await_fallback()
        # greenlet context (Celery worker), which otherwise logs spurious
        # MissingGreenlet errors during pool cleanup.
        _engine = create_async_engine(url, echo=settings.debug, poolclass=NullPool)
    return _engine


def _dispose_engine():
    """Dispose the current engine and drop reference.
    Must be called before asyncio.run() in Celery tasks.
    """
    global _engine
    if _engine is not None:
        try:
            _engine.sync_engine.dispose()
        except Exception:
            pass
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

