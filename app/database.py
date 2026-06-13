from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, echo=settings.debug)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Create tables and enable pgvector extension."""
    # Ensure all models are imported before create_all
    import app.models  # noqa: F401
    async with engine.begin() as conn:
        await conn.execute(__import__("sqlalchemy").text("CREATE EXTENSION IF NOT EXISTS vector"))
        # Add missing columns for existing tables (create_all won't alter them)
        await conn.execute(__import__("sqlalchemy").text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS chat_id BIGINT"
        ))
        # Migrate embedding column from 1536 to 768 dimensions for nomic-embed-text
        # Existing rows have placeholder zero-vectors from the old dimension;
        # nullify them first so pgvector doesn't reject the type change.
        await conn.execute(__import__("sqlalchemy").text(
            "ALTER TABLE posts ALTER COLUMN embedding DROP DEFAULT"
        ))
        await conn.execute(__import__("sqlalchemy").text(
            "UPDATE posts SET embedding = NULL"
        ))
        await conn.execute(__import__("sqlalchemy").text(
            "ALTER TABLE posts ALTER COLUMN embedding TYPE vector(768)"
        ))
        await conn.execute(__import__("sqlalchemy").text(
            "ALTER TABLE posts ALTER COLUMN embedding SET DEFAULT array_fill(0::real, ARRAY[768])::vector"
        ))
        await conn.run_sync(Base.metadata.create_all)
