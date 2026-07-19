from unittest.mock import AsyncMock

import pytest
from telegram.error import BadRequest, Forbidden

from app.services.digest_delivery import (
    UndeliverableChatError,
    format_events_message,
    send_digest_for_user,
)


def test_empty_events_message():
    assert "Нет предстоящих событий" in format_events_message([])


def test_formats_event_with_link():
    events = [{"name": "Конференция", "date": "2026-08-01", "time": "10:00", "link": "https://x"}]
    msg = format_events_message(events)
    assert "*Конференция*" in msg
    assert "2026-08-01" in msg
    assert "[→](https://x)" in msg


def test_event_without_link_has_no_arrow():
    events = [{"name": "Митап", "date": "2026-08-01"}]
    msg = format_events_message(events)
    assert "→" not in msg


def test_limit_caps_number_of_events():
    events = [{"name": f"E{i}", "date": "2026-08-01"} for i in range(20)]
    msg = format_events_message(events, limit=3)
    # header + 3 bullets
    assert msg.count("•") == 3


def test_missing_name_falls_back():
    msg = format_events_message([{"date": "2026-08-01"}])
    assert "Событие" in msg


async def _fake_build_user_digest(*args, **kwargs):
    return {"digest_markdown": "hello"}


@pytest.mark.asyncio
async def test_chat_not_found_raises_undeliverable(monkeypatch):
    """"Chat not found" means the user never opened a chat with the bot (or it
    was deleted) — retrying with plain text would fail identically, so this
    must surface as UndeliverableChatError instead of being swallowed."""
    monkeypatch.setattr(
        "app.services.digest_delivery.build_user_digest", _fake_build_user_digest
    )
    bot = AsyncMock()
    bot.send_message.side_effect = BadRequest("Chat not found")

    with pytest.raises(UndeliverableChatError):
        await send_digest_for_user(bot, 12345678, db=None)
    bot.send_message.assert_awaited_once()  # no plain-text retry — it would fail the same way


@pytest.mark.asyncio
async def test_bot_blocked_raises_undeliverable(monkeypatch):
    monkeypatch.setattr(
        "app.services.digest_delivery.build_user_digest", _fake_build_user_digest
    )
    bot = AsyncMock()
    bot.send_message.side_effect = Forbidden("Forbidden: bot was blocked by the user")

    with pytest.raises(UndeliverableChatError):
        await send_digest_for_user(bot, 12345678, db=None)


@pytest.mark.asyncio
async def test_markdown_rejection_falls_back_to_plain_text(monkeypatch):
    """A genuine Markdown-parsing error (not a permanently-broken chat) should
    still retry as plain text, same as before this change."""
    monkeypatch.setattr(
        "app.services.digest_delivery.build_user_digest", _fake_build_user_digest
    )
    bot = AsyncMock()
    bot.send_message.side_effect = [BadRequest("Can't parse entities: unexpected end of string"), None]

    await send_digest_for_user(bot, 12345678, db=None)
    assert bot.send_message.await_count == 2
