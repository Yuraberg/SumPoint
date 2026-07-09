"""Pure-logic tests for channel failure counting and post export mapping —
no DB required."""
from datetime import datetime
from types import SimpleNamespace

from app.api.posts import _EXPORT_COLUMNS, _export_record
from app.models.channel import Channel
from app.repositories import channel_repository


def _channel(**kw):
    ch = Channel(telegram_id=1, user_id=1, title="X")
    ch.error_count = kw.get("error_count", 0)
    ch.last_error = kw.get("last_error")
    return ch


def test_mark_fetched_success_resets_counter():
    ch = _channel(error_count=5, last_error="boom")
    channel_repository.mark_fetched(ch, datetime(2026, 7, 1))
    assert ch.error_count == 0
    assert ch.last_error is None


def test_mark_fetched_counts_real_failure():
    ch = _channel(error_count=2)
    channel_repository.mark_fetched(ch, datetime(2026, 7, 1), error="entity gone", count_failure=True)
    assert ch.error_count == 3
    assert ch.last_error == "entity gone"


def test_mark_fetched_transient_failure_does_not_count():
    """Flood waits set the error but must not push the counter toward
    auto-deactivation."""
    ch = _channel(error_count=2)
    channel_repository.mark_fetched(ch, datetime(2026, 7, 1), error="flood wait 30s")
    assert ch.error_count == 2  # unchanged
    assert ch.last_error == "flood wait 30s"


def test_export_record_shape_and_link():
    row = SimpleNamespace(
        Post=SimpleNamespace(
            id=7, telegram_message_id=42, published_at=datetime(2026, 7, 1),
            category="Технологии", summary="s", text="t", read_at=datetime(2026, 7, 2)),
        channel_username="chan", channel_title="Chan", cluster_size=3,
    )
    rec = _export_record(row)
    assert set(rec.keys()) == set(_EXPORT_COLUMNS)
    assert rec["telegram_url"] == "https://t.me/chan/42"
    assert rec["is_read"] is True
    assert rec["cluster_size"] == 3


def test_export_record_no_username_no_link():
    row = SimpleNamespace(
        Post=SimpleNamespace(
            id=8, telegram_message_id=1, published_at=datetime(2026, 7, 1),
            category=None, summary=None, text=None, read_at=None),
        channel_username=None, channel_title="Chan", cluster_size=1,
    )
    rec = _export_record(row)
    assert rec["telegram_url"] == ""
    assert rec["is_read"] is False
    assert rec["cluster_size"] == 1
