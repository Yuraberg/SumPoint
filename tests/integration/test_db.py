"""Integration tests — run against a real PostgreSQL with pgvector.

These tests verify that the database schema, Alembic migrations, and
SQL queries work correctly with a real database. They are skipped by
default in unit test runs (run separately with --integration flag or
via the CI integration job).

Usage:
    TEST_DATABASE_URL=postgresql+asyncpg://sumpoint:sumpoint@localhost:5432/sumpoint_test \\
    pytest tests/integration/ -v
"""
import os
import pytest
import pytest_asyncio
from sqlalchemy import text


pytestmark = pytest.mark.asyncio


@pytest.mark.integration
async def test_database_connectivity(db):
    """Verify we can connect and execute a simple query."""
    result = await db.execute(text("SELECT 1"))
    assert result.scalar() == 1


@pytest.mark.integration
async def test_pgvector_extension(db):
    """Verify pgvector extension is installed."""
    result = await db.execute(
        text("SELECT installed_version FROM pg_available_extensions WHERE name = 'vector'")
    )
    version = result.scalar()
    assert version is not None, "pgvector extension not available"


@pytest.mark.integration
async def test_create_and_query_user(db):
    """Verify we can insert and query a user in a real DB."""
    from app.models.user import User
    from app.repositories import user_repository

    user = await user_repository.get_or_create(
        db,
        user_id=999888,
        first_name="Integration",
        username="testuser",
        chat_id=111222,
    )
    assert user.id == 999888
    assert user.first_name == "Integration"

    # Query back
    result = await db.execute(
        text("SELECT first_name FROM users WHERE id = :uid"),
        {"uid": 999888},
    )
    assert result.scalar() == "Integration"


@pytest.mark.integration
async def test_user_idempotency(db):
    """Verify get_or_create is idempotent with real DB."""
    from app.repositories import user_repository

    user1 = await user_repository.get_or_create(
        db, user_id=42, first_name="Alice", username="alice", chat_id=1
    )
    user2 = await user_repository.get_or_create(
        db, user_id=42, first_name="Alice_Updated", username="alice2", chat_id=2
    )

    assert user2.id == 42
    assert user2.first_name == "Alice_Updated"  # should refresh
    assert user2.username == "alice2"
    assert user2.chat_id == 2
