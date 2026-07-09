"""Retrieval-Augmented Generation over the user's own posts.

Flow: embed the question (BGE-M3) → retrieve the most relevant posts via
pgvector cosine search → feed them as context to DeepSeek → return the grounded
answer plus the sources it was built from.

Graceful degradation without BGE-M3: an unavailable Ollama yields a zero-vector
query embedding, which makes cosine ordering meaningless. We detect that with
``is_usable_embedding`` and fall back to ILIKE keyword search so the assistant
still returns *something* relevant instead of noise.
"""
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import post_repository
from app.services.ai_engine import answer_from_context, generate_embedding
from app.services.clustering import is_usable_embedding

logger = logging.getLogger(__name__)

TOP_K = 8
SNIPPET_CHARS = 600
NO_CONTEXT_ANSWER = (
    "В твоих постах нет информации по этому вопросу. "
    "Попробуй переформулировать или добавить больше каналов."
)


def _semantic_source(row) -> dict:
    return {
        "id": row.id,
        "channel_id": row.channel_id,
        "telegram_message_id": row.telegram_message_id,
        "channel_username": row.channel_username,
        "channel_title": row.channel_title,
        "published_at": row.published_at,
        "snippet": (row.summary or row.text or "")[:SNIPPET_CHARS],
    }


def _keyword_source(row) -> dict:
    post = row.Post
    return {
        "id": post.id,
        "channel_id": post.channel_id,
        "telegram_message_id": post.telegram_message_id,
        "channel_username": row.channel_username,
        "channel_title": row.channel_title,
        "published_at": post.published_at,
        "snippet": (post.summary or post.text or "")[:SNIPPET_CHARS],
    }


def _build_context(sources: list[dict]) -> str:
    lines = []
    for i, s in enumerate(sources, start=1):
        date = s["published_at"].strftime("%d.%m.%Y") if s["published_at"] else ""
        title = s["channel_title"] or s["channel_username"] or "—"
        lines.append(f"[{i}] {title} ({date}): {s['snippet']}")
    return "\n\n".join(lines)


async def answer_question(db: AsyncSession, user_id: int, question: str) -> dict:
    """Return ``{"answer": str, "sources": list[dict]}`` for the question,
    grounded in the user's own posts."""
    embedding = await generate_embedding(question)

    if is_usable_embedding(embedding):
        rows = await post_repository.semantic_search(db, user_id, embedding, limit=TOP_K)
        sources = [_semantic_source(r) for r in rows]
    else:
        logger.info("RAG: embedding unavailable, falling back to keyword search")
        rows = await post_repository.keyword_search(
            db, user_id, question, limit=TOP_K, include_summary=True
        )
        sources = [_keyword_source(r) for r in rows]

    if not sources:
        return {"answer": NO_CONTEXT_ANSWER, "sources": []}

    answer = await answer_from_context(question, _build_context(sources))
    return {"answer": answer, "sources": sources}
