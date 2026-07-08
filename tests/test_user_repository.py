"""Unit tests for user_repository.get_or_create with a stubbed session.

This consolidates four previously duplicated user-creation blocks (three auth
endpoints + the bot /start handler), so its idempotency and field-refresh
behaviour is worth pinning down without a live database.
"""
import pytest

from app.models.user import User
from app.repositories import user_repository


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeSession:
    """Minimal async session stub: returns a preset user from execute(),
    records add()s, and counts flush() calls."""
    def __init__(self, existing_user=None):
        self._existing = existing_user
        self.added = []
        self.flushed = 0

    async def execute(self, _stmt):
        return _FakeResult(self._existing)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed += 1


@pytest.mark.asyncio
async def test_creates_user_when_absent():
    db = _FakeSession(existing_user=None)
    user = await user_repository.get_or_create(
        db, 42, first_name="Alice", username="alice", chat_id=99
    )
    assert isinstance(user, User)
    assert user.id == 42
    assert user.first_name == "Alice"
    assert user.username == "alice"
    assert user.chat_id == 99
    assert db.added == [user]
    assert db.flushed == 1


@pytest.mark.asyncio
async def test_blank_first_name_defaults():
    db = _FakeSession(existing_user=None)
    user = await user_repository.get_or_create(db, 42, first_name="")
    assert user.first_name == "User"


@pytest.mark.asyncio
async def test_returns_existing_and_refreshes_fields():
    existing = User(id=42, first_name="Bob", username=None, chat_id=None)
    db = _FakeSession(existing_user=existing)
    user = await user_repository.get_or_create(
        db, 42, first_name="Bob Updated", username="bob", chat_id=123
    )
    assert user is existing
    assert user.first_name == "Bob Updated"  # refreshed — Telegram display names change
    assert user.username == "bob"            # refreshed
    assert user.chat_id == 123               # refreshed
    assert db.added == []                    # not re-added
    assert db.flushed == 0                   # no flush for existing rows


@pytest.mark.asyncio
async def test_existing_user_missing_optional_fields_left_alone():
    existing = User(id=7, first_name="Carol", username="carol", chat_id=5)
    db = _FakeSession(existing_user=existing)
    user = await user_repository.get_or_create(db, 7, first_name="")
    # Nothing truthy supplied → keep the current values.
    assert user.first_name == "Carol"
    assert user.username == "carol"
    assert user.chat_id == 5
