"""RAG service: context assembly, source normalisation, and the BGE-M3-down
keyword fallback — all without touching a real DB, embedding model, or DeepSeek."""
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.services import rag_service


def test_build_context_numbers_sources():
    sources = [
        {"channel_title": "Tech", "channel_username": "tech",
         "published_at": datetime(2026, 7, 1), "snippet": "AI news"},
        {"channel_title": None, "channel_username": "biz",
         "published_at": datetime(2026, 7, 2), "snippet": "market"},
    ]
    ctx = rag_service._build_context(sources)
    assert "[1] Tech (01.07.2026): AI news" in ctx
    assert "[2] biz (02.07.2026): market" in ctx


def test_semantic_and_keyword_sources_have_same_shape():
    sem = rag_service._semantic_source(SimpleNamespace(
        id=1, channel_id=10, telegram_message_id=5, channel_username="c",
        channel_title="C", published_at=datetime(2026, 7, 1),
        summary="sum", text="body"))
    kw = rag_service._keyword_source(SimpleNamespace(
        Post=SimpleNamespace(id=1, channel_id=10, telegram_message_id=5,
                             published_at=datetime(2026, 7, 1), summary="sum", text="body"),
        channel_username="c", channel_title="C"))
    assert sem.keys() == kw.keys()
    assert sem["snippet"] == kw["snippet"] == "sum"  # summary preferred over text


@pytest.mark.asyncio
async def test_answer_question_uses_semantic_when_embedding_usable(monkeypatch):
    captured = {}

    async def fake_embed(_q):
        return [0.5] * 4  # usable, non-zero

    async def fake_semantic(db, uid, emb, *, limit):
        captured["path"] = "semantic"
        return [SimpleNamespace(id=1, channel_id=10, telegram_message_id=5,
                                channel_username="c", channel_title="C",
                                published_at=datetime(2026, 7, 1), summary="s", text="t")]

    async def fake_answer(question, context):
        captured["context"] = context
        return "Ответ [1]"

    monkeypatch.setattr(rag_service, "generate_embedding", fake_embed)
    monkeypatch.setattr(rag_service.post_repository, "semantic_search", fake_semantic)
    monkeypatch.setattr(rag_service, "answer_from_context", fake_answer)

    res = await rag_service.answer_question(db=None, user_id=1, question="что нового?")
    assert captured["path"] == "semantic"
    assert res["answer"] == "Ответ [1]"
    assert len(res["sources"]) == 1
    assert "[1] C" in captured["context"]


@pytest.mark.asyncio
async def test_answer_question_falls_back_to_keyword_without_embeddings(monkeypatch):
    captured = {}

    async def fake_embed(_q):
        return [0.0] * 4  # zero-vector → BGE-M3 unavailable

    async def fake_keyword(db, uid, q, *, limit, include_summary):
        captured["path"] = "keyword"
        return [SimpleNamespace(
            Post=SimpleNamespace(id=2, channel_id=20, telegram_message_id=9,
                                 published_at=datetime(2026, 7, 3), summary="kw", text="t"),
            channel_username="d", channel_title="D")]

    async def fake_semantic(*a, **k):
        raise AssertionError("semantic_search must not be called on zero-vector")

    async def fake_answer(question, context):
        return "keyword answer"

    monkeypatch.setattr(rag_service, "generate_embedding", fake_embed)
    monkeypatch.setattr(rag_service.post_repository, "keyword_search", fake_keyword)
    monkeypatch.setattr(rag_service.post_repository, "semantic_search", fake_semantic)
    monkeypatch.setattr(rag_service, "answer_from_context", fake_answer)

    res = await rag_service.answer_question(db=None, user_id=1, question="вакансии?")
    assert captured["path"] == "keyword"
    assert res["answer"] == "keyword answer"


@pytest.mark.asyncio
async def test_answer_question_no_sources_short_circuits(monkeypatch):
    async def fake_embed(_q):
        return [0.5] * 4

    async def fake_semantic(*a, **k):
        return []

    called = {"llm": False}

    async def fake_answer(*a, **k):
        called["llm"] = True
        return "should not run"

    monkeypatch.setattr(rag_service, "generate_embedding", fake_embed)
    monkeypatch.setattr(rag_service.post_repository, "semantic_search", fake_semantic)
    monkeypatch.setattr(rag_service, "answer_from_context", fake_answer)

    res = await rag_service.answer_question(db=None, user_id=1, question="x")
    assert res["sources"] == []
    assert res["answer"] == rag_service.NO_CONTEXT_ANSWER
    assert called["llm"] is False  # no LLM call when nothing was retrieved
