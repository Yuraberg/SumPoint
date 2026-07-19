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
async def test_digest_subscribers_excludes_users_without_chat_id(db):
    """A web-only signup (Login Widget / magic link / Mini App) never gets a
    chat_id — only the bot's /start handler sets it. digest_morning defaults
    to True regardless of signup flow, so without this filter such a user
    would be queried here every slot and fail permanently with Telegram's
    "Chat not found" (see app/repositories/user_repository.py)."""
    from app.repositories import user_repository

    await user_repository.get_or_create(
        db, user_id=555001, first_name="WebOnly", chat_id=None,
    )
    await user_repository.get_or_create(
        db, user_id=555002, first_name="BotUser", chat_id=555002,
    )
    await db.flush()

    subscribers = await user_repository.get_digest_subscribers(db, "morning")
    subscriber_ids = {u.id for u in subscribers}

    assert 555002 in subscriber_ids
    assert 555001 not in subscriber_ids


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


@pytest.mark.integration
async def test_stats_aggregates_and_ownership(engine, _create_tables):
    """Statistics repository: totals, per-day, per-category, per-channel and
    channel_health — all scoped to the owning user."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.models.channel import Channel
    from app.models.post import Post
    from app.models.user import User
    from app.repositories import stats_repository
    from app.utils.time import utcnow

    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as db:
        db.add_all([User(id=1, first_name="Alice"), User(id=2, first_name="Bob")])
        await db.flush()
        db.add_all([
            Channel(id=10, telegram_id=100, user_id=1, title="News"),
            Channel(id=11, telegram_id=101, user_id=1, title="Tech"),
            Channel(id=20, telegram_id=200, user_id=2, title="Bob"),
        ])
        await db.flush()

        now = utcnow()
        # Alice: 2 "news" posts (one unread, one read), 1 "tech" post with events,
        # plus 1 ad that must be excluded everywhere.
        db.add_all([
            Post(channel_id=10, telegram_message_id=1, text="a1", category="news",
                 published_at=now, is_ad=False),
            Post(channel_id=10, telegram_message_id=2, text="a2", category="news",
                 published_at=now, is_ad=False, read_at=now),
            Post(channel_id=11, telegram_message_id=3, text="a3", category="tech",
                 published_at=now, is_ad=False, events=[{"name": "x"}]),
            Post(channel_id=10, telegram_message_id=4, text="ad", category="ad",
                 published_at=now, is_ad=True),
            # Bob's post — never counted for Alice.
            Post(channel_id=20, telegram_message_id=9, text="b", category="news",
                 published_at=now, is_ad=False),
        ])
        await db.commit()

        totals = await stats_repository.totals(db, 1)
        assert totals == {"posts": 3, "unread": 2, "events": 1, "channels": 2}

        per_cat = await stats_repository.posts_per_category(db, 1)
        assert {r["category"]: r["count"] for r in per_cat} == {"news": 2, "tech": 1}

        per_chan = {r["title"]: r["count"]
                    for r in await stats_repository.posts_per_channel(db, 1)}
        assert per_chan == {"News": 2, "Tech": 1}

        per_day = await stats_repository.posts_per_day(db, 1, days=7)
        assert len(per_day) == 7  # zero-filled
        assert sum(r["count"] for r in per_day) == 3

        health = {h["title"]: h
                  for h in await stats_repository.channel_health(db, 1)}
        assert health["News"]["post_count"] == 2
        assert health["News"]["unread_count"] == 1
        assert health["Tech"]["post_count"] == 1
        assert "Bob" not in health  # ownership scoping


@pytest.mark.integration
async def test_duplicate_clustering(engine, _create_tables):
    """assign_cluster groups near-identical embeddings across a user's channels,
    keeps distinct posts apart, never merges zero-vector (BGE-M3 down) posts, and
    the feed reports the right cluster_size — all owner-scoped."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.constants import EMBEDDING_DIM
    from app.models.channel import Channel
    from app.models.post import Post
    from app.models.user import User
    from app.repositories import post_repository
    from app.services.clustering import assign_cluster
    from app.utils.time import utcnow

    def vec(*head):
        v = [0.0] * EMBEDDING_DIM
        for i, x in enumerate(head):
            v[i] = float(x)
        return v

    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as db:
        db.add_all([User(id=1, first_name="Alice"), User(id=2, first_name="Bob")])
        await db.flush()
        db.add_all([
            Channel(id=10, telegram_id=100, user_id=1, title="A"),
            Channel(id=11, telegram_id=101, user_id=1, title="B"),
            Channel(id=20, telegram_id=200, user_id=2, title="Bob"),
        ])
        await db.flush()

        now = utcnow()
        # Two near-identical stories in different channels, one distinct story,
        # and one with a zero-vector (embedding unavailable).
        p_a = Post(channel_id=10, telegram_message_id=1, text="dup", published_at=now,
                   is_ad=False, embedding=vec(1.0, 0.01))
        p_b = Post(channel_id=11, telegram_message_id=2, text="dup", published_at=now,
                   is_ad=False, embedding=vec(1.0, 0.02))
        p_c = Post(channel_id=10, telegram_message_id=3, text="other", published_at=now,
                   is_ad=False, embedding=vec(0.0, 1.0))
        p_z1 = Post(channel_id=10, telegram_message_id=4, text="z1", published_at=now,
                    is_ad=False, embedding=vec())          # zero vector
        p_z2 = Post(channel_id=11, telegram_message_id=5, text="z2", published_at=now,
                    is_ad=False, embedding=vec())          # zero vector
        for p in (p_a, p_b, p_c, p_z1, p_z2):
            db.add(p)
            await db.flush()
            await assign_cluster(db, p, 1)
        await db.commit()

        # Near-identical posts landed in the same cluster.
        assert p_a.cluster_id == p_b.cluster_id
        # The distinct post is its own singleton cluster.
        assert p_c.cluster_id == p_c.id
        assert p_c.cluster_id != p_a.cluster_id
        # Zero-vector posts stay singletons and never merge with each other.
        assert p_z1.cluster_id == p_z1.id
        assert p_z2.cluster_id == p_z2.id
        assert p_z1.cluster_id != p_z2.cluster_id

        # Feed cluster_size: the duplicated story spans 2 channels; others = 1.
        rows = {r.Post.id: r.cluster_size
                for r in await post_repository.list_for_user(db, 1)}
        assert rows[p_a.id] == 2
        assert rows[p_b.id] == 2
        assert rows[p_c.id] == 1
        assert rows[p_z1.id] == 1

        # Cluster members are owner-scoped and list every source in the cluster.
        members = await post_repository.get_cluster_members(db, 1, p_a.cluster_id)
        assert {m.id for m in members} == {p_a.id, p_b.id}
        assert await post_repository.get_cluster_members(db, 2, p_a.cluster_id) == []


@pytest.mark.integration
async def test_access_control_signup_and_invite_flow(db, monkeypatch):
    """login_or_signup's approval decision (owner allowlist / invite code /
    pending) and invite-code single-use consumption, against a real DB."""
    from app.config import get_settings
    from app.repositories import invite_repository, user_repository

    # owner_telegram_id_set is a computed property over the owner_telegram_ids
    # field; patching the underlying field on the lru_cache'd Settings
    # singleton affects every caller for the duration of this test.
    monkeypatch.setattr(get_settings(), "owner_telegram_ids", "1")

    # Owner (id=1) is auto-approved on first login, no invite code needed.
    owner = await user_repository.login_or_signup(db, 1, first_name="Owner")
    assert owner.is_approved is True

    # Stranger with no code lands pending.
    stranger = await user_repository.login_or_signup(db, 2, first_name="Stranger")
    assert stranger.is_approved is False

    # A valid invite code auto-approves a brand-new signup and gets consumed.
    invite = await invite_repository.create(db, created_by=1, max_uses=1)
    await db.flush()
    invitee = await user_repository.login_or_signup(
        db, 3, first_name="Invitee", invite_code=invite.code
    )
    assert invitee.is_approved is True

    # The same code is single-use: a second signup with it stays pending.
    latecomer = await user_repository.login_or_signup(
        db, 4, first_name="Latecomer", invite_code=invite.code
    )
    assert latecomer.is_approved is False

    # Logging in again (existing user) never re-evaluates or re-burns a code.
    again = await user_repository.login_or_signup(
        db, 2, first_name="Stranger", invite_code=invite.code
    )
    assert again.is_approved is False
