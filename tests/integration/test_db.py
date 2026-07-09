"""Integration tests — run against a real PostgreSQL with pgvector.

These tests verify that the database schema, Alembic migrations, and
SQL queries work correctly with a real database. They are skipped by
default in unit test runs (run separately with --integration flag or
via the CI integration job).

Usage:
    TEST_DATABASE_URL=postgresql+asyncpg://sumpoint:sumpoint@localhost:5432/sumpoint_test \\
    pytest tests/integration/ -v
"""
import pytest
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

    await user_repository.get_or_create(
        db, user_id=42, first_name="Alice", username="alice", chat_id=1
    )
    user2 = await user_repository.get_or_create(
        db, user_id=42, first_name="Alice_Updated", username="alice2", chat_id=2
    )

    assert user2.id == 42
    assert user2.first_name == "Alice_Updated"  # should refresh
    assert user2.username == "alice2"
    assert user2.chat_id == 2


@pytest.mark.integration
async def test_unread_flow_and_ownership(engine, _create_tables):
    """count_unread / mark_read / mark_all_read against a real DB, and the
    security property that one user can't mark another user's posts read."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.models.channel import Channel
    from app.models.post import Post
    from app.models.user import User
    from app.repositories import post_repository

    # mark_read/mark_all_read commit internally, so use a plain session rather
    # than the transaction-wrapped `db` fixture.
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as db:
        alice = User(id=1, first_name="Alice")
        bob = User(id=2, first_name="Bob")
        db.add_all([alice, bob])
        await db.flush()

        ch_a = Channel(id=10, telegram_id=100, user_id=1, title="A")
        ch_b = Channel(id=20, telegram_id=200, user_id=2, title="B")
        db.add_all([ch_a, ch_b])
        await db.flush()

        from app.utils.time import utcnow
        for i in range(3):
            db.add(Post(channel_id=10, telegram_message_id=i, text=f"a{i}",
                        published_at=utcnow(), is_ad=False))
        db.add(Post(channel_id=20, telegram_message_id=99, text="b0",
                    published_at=utcnow(), is_ad=False))
        await db.commit()

        alice_posts = [r.Post.id for r in await post_repository.list_for_user(db, 1)]
        bob_post = (await post_repository.list_for_user(db, 2))[0].Post.id

        assert await post_repository.count_unread(db, 1) == 3

        # Alice marks one of her own posts read.
        assert await post_repository.mark_read(db, 1, [alice_posts[0]]) == 1
        assert await post_repository.count_unread(db, 1) == 2

        # Alice tries to mark Bob's post read — ignored, no rows affected.
        assert await post_repository.mark_read(db, 1, [bob_post]) == 0
        assert await post_repository.count_unread(db, 2) == 1

        # mark_all_read clears the rest of Alice's, leaving Bob's untouched.
        assert await post_repository.mark_all_read(db, 1) == 2
        assert await post_repository.count_unread(db, 1) == 0
        assert await post_repository.count_unread(db, 2) == 1
