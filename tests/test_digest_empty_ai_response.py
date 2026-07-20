"""Regression tests for the "AI returned empty digest" vs "no posts" mixup.

DeepSeek occasionally answers with empty content (HTTP 200, no exception) for
large digest prompts. The old code treated that the same as "no posts found",
so users with hundreds of unread posts saw "Нет новых постов." — see
generate_digest_text / build_user_digest.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.services import ai_engine, digest_service


def _fake_response(content: str, finish_reason: str = "stop"):
    message = type("Message", (), {"content": content})()
    choice = type("Choice", (), {"message": message, "finish_reason": finish_reason})()
    return type("Response", (), {"choices": [choice]})()


async def test_generate_digest_text_retries_once_on_empty_response():
    calls = iter([_fake_response(""), _fake_response("# Digest\n- real content")])
    with patch.object(ai_engine, "_call_raw", AsyncMock(side_effect=lambda *a, **k: next(calls))):
        text = await ai_engine.generate_digest_text([{"channel": "c", "summary": "s", "category": "Прочее"}])
    assert text == "# Digest\n- real content"


async def test_generate_digest_text_returns_empty_if_retry_also_empty():
    with patch.object(ai_engine, "_call_raw", AsyncMock(return_value=_fake_response(""))):
        text = await ai_engine.generate_digest_text([{"channel": "c", "summary": "s", "category": "Прочее"}])
    assert text == ""


async def test_generate_digest_text_trims_truncated_tail_and_notes_it():
    """finish_reason == "length" means DeepSeek ran out of output tokens
    mid-generation — the trailing (incomplete) line must be dropped and a
    note appended, instead of shipping a digest that just stops mid-word."""
    cut_off = "# Digest\n## Технологии\n- Channel A: full summary\n- Channel B: <"
    with patch.object(ai_engine, "_call_raw", AsyncMock(return_value=_fake_response(cut_off, "length"))):
        text = await ai_engine.generate_digest_text([{"channel": "c", "summary": "s", "category": "Прочее"}])
    assert "Channel B" not in text
    assert "Channel A: full summary" in text
    assert "обрезан" in text


async def test_generate_digest_text_drops_empty_summaries_from_prompt():
    """Posts with no summary would otherwise show up as bare "Channel: "
    bullets — exclude them from the prompt sent to DeepSeek entirely."""
    captured = {}

    async def _capture(prompt, **kwargs):
        captured["prompt"] = prompt
        return _fake_response("# Digest\n- ok")

    with patch.object(ai_engine, "_call_raw", AsyncMock(side_effect=_capture)):
        await ai_engine.generate_digest_text([
            {"channel": "HasSummary", "summary": "real content", "category": "Прочее"},
            {"channel": "NoSummary", "summary": "", "category": "Прочее"},
        ])
    assert "HasSummary" in captured["prompt"]
    assert "NoSummary" not in captured["prompt"]


async def test_build_user_digest_raises_when_posts_exist_but_ai_returns_empty():
    fake_post = type("P", (), {
        "id": 1, "channel_id": 1, "telegram_message_id": 1, "text": "t",
        "published_at": None, "summary": "s", "category": "Прочее",
        "is_ad": False, "events": None,
    })()
    fake_row = type("Row", (), {"Post": fake_post, "channel_title": "chan"})()

    with (
        patch.object(digest_service.post_repository, "get_digest_feed", AsyncMock(return_value=[fake_row])),
        patch.object(digest_service, "generate_digest_text", AsyncMock(return_value="")),
        pytest.raises(RuntimeError),
    ):
        await digest_service.build_user_digest(db=None, user_id=1)


async def test_build_user_digest_returns_none_markdown_when_no_posts():
    with patch.object(digest_service.post_repository, "get_digest_feed", AsyncMock(return_value=[])):
        result = await digest_service.build_user_digest(db=None, user_id=1)
    assert result["digest_markdown"] is None
