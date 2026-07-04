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


def _patch_feed(monkeypatch, rows):
    async def fake_feed(db, user_id):
        return rows
    monkeypatch.setattr(calendar_service.post_repository, "get_events_feed", fake_feed)


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
