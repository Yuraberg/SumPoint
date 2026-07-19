"""Unit tests for favorite_repository.toggle with a stubbed session — pins
down the ownership check and the event_index bounds check without a live DB.
"""
import pytest

from app.models.favorite import WHOLE_POST, Favorite
from app.models.post import Post
from app.repositories import favorite_repository


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeSession:
    """Returns queued results from successive execute() calls, in order —
    toggle() issues an ownership lookup, then a check for an existing
    favorite row."""
    def __init__(self, results):
        self._results = list(results)
        self.added = []
        self.deleted = []
        self.commits = 0

    async def execute(self, _stmt):
        return _FakeResult(self._results.pop(0))

    def add(self, obj):
        self.added.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def commit(self):
        self.commits += 1


def _post(id=1, events=None):
    return Post(id=id, channel_id=1, telegram_message_id=1, events=events)


@pytest.mark.asyncio
async def test_toggle_raises_lookuperror_for_unowned_post():
    db = _FakeSession(results=[None])  # ownership query finds nothing
    with pytest.raises(LookupError):
        await favorite_repository.toggle(db, user_id=1, post_id=99)


@pytest.mark.asyncio
async def test_toggle_raises_lookuperror_for_out_of_range_event_index():
    post = _post(events=[{"name": "A"}])
    db = _FakeSession(results=[post])  # ownership query succeeds; index 5 is out of range
    with pytest.raises(LookupError):
        await favorite_repository.toggle(db, user_id=1, post_id=1, event_index=5)


@pytest.mark.asyncio
async def test_toggle_accepts_valid_event_index():
    post = _post(events=[{"name": "A"}, {"name": "B"}])
    db = _FakeSession(results=[post, None])  # owned post, no existing favorite for index 1
    result = await favorite_repository.toggle(db, user_id=1, post_id=1, event_index=1)
    assert result is True
    assert db.added[0].event_index == 1


@pytest.mark.asyncio
async def test_toggle_adds_favorite_when_absent():
    post = _post()
    db = _FakeSession(results=[post, None])  # owned post, no existing favorite
    result = await favorite_repository.toggle(db, user_id=1, post_id=1)
    assert result is True
    assert len(db.added) == 1
    assert db.added[0].post_id == 1
    assert db.added[0].user_id == 1
    assert db.added[0].event_index == WHOLE_POST
    assert db.commits == 1


@pytest.mark.asyncio
async def test_toggle_removes_favorite_when_present():
    post = _post()
    existing = Favorite(id=5, user_id=1, post_id=1, event_index=WHOLE_POST)
    db = _FakeSession(results=[post, existing])
    result = await favorite_repository.toggle(db, user_id=1, post_id=1)
    assert result is False
    assert db.deleted == [existing]
    assert db.added == []
    assert db.commits == 1
