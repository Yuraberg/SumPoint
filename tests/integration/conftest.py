"""Integration test fixtures — real PostgreSQL + pgvector.

These tests require a running PostgreSQL instance with pgvector extension.
In CI, this is provided by the pgvector service container.
Locally, point DATABASE_URL to your dev database.
"""
import os
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text

from app.database import Base
from app.models.user import User  # noqa: F401 — ensure models are loaded


# Override test defaults with a database that actually exists
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://sumpoint:sumpoint@localhost:5432/sumpoint_test",
)


@pytest_asyncio.fixture(scope="session")
async def engine():
    """Create a test database engine (session-scoped)."""
    eng = create_async_engine(TEST_DB_URL, echo=False)

    # Create pgvector extension if needed
    async with eng.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    yield eng
    await eng.dispose()


@pytest_asyncio.fixture(scope="session")
async def _create_tables(engine):
    """Create all tables once per test session."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db(engine, _create_tables):
    """Provide a fresh transaction-rolled-back session per test."""
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        async with session.begin():
            yield session
            await session.rollback()
