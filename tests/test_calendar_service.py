"""Unit tests for calendar_service.get_upcoming_events.

The DB query is stubbed via the repository so these run without Postgres — they
exercise the date filtering, event-type filtering, name+date dedup, mention
counting, sorting, and malformed-event tolerance.
"""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.services import calendar_service


def _row(events, category="Технологии", title="Ch", username="ch"):
    """Mimic a repository row: attribute access to events/category/channel_*."""
    return SimpleNamespace(
        id=1, events=events, category=category,
        channel_title=title, channel_username=username,
    )


def _patch_feed(monkeypatch, rows, favorite_keys=frozenset()):
    async def fake_feed(db, user_id):
        return rows
    monkeypatch.setattr(calendar_service.post_repository, "get_events_feed", fake_feed)

    async def fake_favorite_keys(db, user_id):
        return set(favorite_keys)
    monkeypatch.setattr(calendar_service.favorite_repository, "get_favorite_event_keys", fake_favorite_keys)


def _iso(d: date) -> str:
    return d.isoformat()


@pytest.mark.asyncio
async def test_returns_events_within_window(monkeypatch):
    soon = date.today() + timedelta(days=2)
    _patch_feed(monkeypatch, [_row([{"name": "Конференция", "date": _iso(soon)}])])
    events = await calendar_service.get_upcoming_events(None, user_id=1, days_ahead=7)
    assert len(events) == 1
    assert events[0]["name"] == "Конференция"
    assert events[0]["channel_title"] == "Ch"


@pytest.mark.asyncio
async def test_excludes_events_outside_window(monkeypatch):
    far = date.today() + timedelta(days=100)
    _patch_feed(monkeypatch, [_row([{"name": "Далеко", "date": _iso(far)}])])
    events = await calendar_service.get_upcoming_events(None, user_id=1, days_ahead=7)
    assert events == []


@pytest.mark.asyncio
async def test_event_type_filter(monkeypatch):
    soon = date.today() + timedelta(days=1)
    rows = [
        _row([{"name": "Вебинар", "date": _iso(soon), "type": "webinar"}]),
        _row([{"name": "Митап", "date": _iso(soon), "type": "meetup"}]),
    ]
    _patch_feed(monkeypatch, rows)
    events = await calendar_service.get_upcoming_events(
        None, user_id=1, days_ahead=7, event_type="webinar"
    )
    assert [e["name"] for e in events] == ["Вебинар"]


@pytest.mark.asyncio
async def test_same_name_different_dates_kept_distinct(monkeypatch):
    d1 = date.today() + timedelta(days=1)
    d2 = date.today() + timedelta(days=2)
    rows = [
        _row([{"name": "Сходка", "date": _iso(d1)}]),
        _row([{"name": "Сходка", "date": _iso(d2)}]),
    ]
    _patch_feed(monkeypatch, rows)
    events = await calendar_service.get_upcoming_events(None, user_id=1, days_ahead=7)
    assert len(events) == 2


@pytest.mark.asyncio
async def test_same_name_same_date_deduped_with_mentions(monkeypatch):
    d1 = date.today() + timedelta(days=1)
    rows = [
        _row([{"name": "Форум", "date": _iso(d1)}], title="A"),
        _row([{"name": "форум", "date": _iso(d1)}], title="B"),
    ]
    _patch_feed(monkeypatch, rows)
    events = await calendar_service.get_upcoming_events(None, user_id=1, days_ahead=7)
    assert len(events) == 1
    assert events[0]["mentions"] == 2


@pytest.mark.asyncio
async def test_results_sorted_by_date(monkeypatch):
    d1 = date.today() + timedelta(days=1)
    d2 = date.today() + timedelta(days=3)
    rows = [
        _row([{"name": "Позже", "date": _iso(d2)}]),
        _row([{"name": "Раньше", "date": _iso(d1)}]),
    ]
    _patch_feed(monkeypatch, rows)
    events = await calendar_service.get_upcoming_events(None, user_id=1, days_ahead=7)
    assert [e["name"] for e in events] == ["Раньше", "Позже"]


@pytest.mark.asyncio
async def test_malformed_events_are_ignored(monkeypatch):
    soon = date.today() + timedelta(days=1)
    rows = [
        _row("not-a-list"),                       # events is a string
        _row([None, 42, "x"]),                    # non-dict entries
        _row([{"name": "OK", "date": _iso(soon)}]),
    ]
    _patch_feed(monkeypatch, rows)
    events = await calendar_service.get_upcoming_events(None, user_id=1, days_ahead=7)
    assert [e["name"] for e in events] == ["OK"]


@pytest.mark.asyncio
async def test_bad_date_string_kept_and_sorted_last(monkeypatch):
    soon = date.today() + timedelta(days=1)
    rows = [
        _row([{"name": "Плохая дата", "date": "не дата"}]),
        _row([{"name": "Хорошая", "date": _iso(soon)}]),
    ]
    _patch_feed(monkeypatch, rows)
    events = await calendar_service.get_upcoming_events(None, user_id=1, days_ahead=7)
    names = [e["name"] for e in events]
    assert "Хорошая" in names and "Плохая дата" in names
    # Unparseable date is not filtered out and sorts to the end.
    assert names[0] == "Хорошая"


@pytest.mark.asyncio
async def test_events_carry_post_id_and_index_for_favoriting(monkeypatch):
    soon = date.today() + timedelta(days=1)
    rows = [_row([
        {"name": "A", "date": _iso(soon)},
        {"name": "B", "date": _iso(soon)},
    ])]
    _patch_feed(monkeypatch, rows)
    events = await calendar_service.get_upcoming_events(None, user_id=1, days_ahead=7)
    by_name = {e["name"]: e for e in events}
    assert by_name["A"]["post_id"] == 1 and by_name["A"]["event_index"] == 0
    assert by_name["B"]["post_id"] == 1 and by_name["B"]["event_index"] == 1


@pytest.mark.asyncio
async def test_is_favorite_annotated_from_favorite_keys(monkeypatch):
    soon = date.today() + timedelta(days=1)
    rows = [_row([{"name": "Избранное", "date": _iso(soon)}, {"name": "Обычное", "date": _iso(soon)}])]
    _patch_feed(monkeypatch, rows, favorite_keys={(1, 0)})
    events = await calendar_service.get_upcoming_events(None, user_id=1, days_ahead=7)
    by_name = {e["name"]: e for e in events}
    assert by_name["Избранное"]["is_favorite"] is True
    assert by_name["Обычное"]["is_favorite"] is False


class _FakePost:
    def __init__(self, id, events, category="Технологии"):
        self.id = id
        self.events = events
        self.category = category


def _fav_row(post_id, events, event_index, *, title="Ch", username="ch", category="Технологии", favorited_at="t"):
    return SimpleNamespace(
        Post=_FakePost(post_id, events, category=category),
        event_index=event_index,
        channel_title=title,
        channel_username=username,
        favorited_at=favorited_at,
    )


@pytest.mark.asyncio
async def test_get_favorite_events_extracts_event_by_index(monkeypatch):
    events = [{"name": "Первое", "date": "2026-08-01"}, {"name": "Второе", "date": "2026-08-02"}]
    rows = [_fav_row(1, events, 1)]

    async def fake_list(db, user_id):
        return rows
    monkeypatch.setattr(calendar_service.favorite_repository, "list_favorite_events", fake_list)

    result = await calendar_service.get_favorite_events(None, user_id=1)
    assert len(result) == 1
    assert result[0]["name"] == "Второе"
    assert result[0]["is_favorite"] is True
    assert result[0]["post_id"] == 1
    assert result[0]["event_index"] == 1


@pytest.mark.asyncio
async def test_get_favorite_events_skips_stale_out_of_range_index(monkeypatch):
    """A favorite pointing past the events array (e.g. the post was re-processed
    with fewer events, which never happens today but is cheap to guard) is
    silently dropped rather than raising an IndexError."""
    rows = [_fav_row(1, [{"name": "Только одно", "date": "2026-08-01"}], event_index=5)]

    async def fake_list(db, user_id):
        return rows
    monkeypatch.setattr(calendar_service.favorite_repository, "list_favorite_events", fake_list)

    result = await calendar_service.get_favorite_events(None, user_id=1)
    assert result == []
