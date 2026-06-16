""" /search command — ILIKE + pgvector semantic search over posts. """

import logging
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select, or_, text

from app.database import AsyncSessionLocal
from app.models.post import Post
from app.models.channel import Channel
from app.services.ai_engine import generate_embedding

logger = logging.getLogger(__name__)


async def search_posts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Search posts by query. Usage: /search <text>"""
    query_text = " ".join(context.args) if context.args else ""
    if not query_text:
        await update.message.reply_text(
            "🔍 *Поиск*\n\nНапишите запрос после /search:\n`/search умный дом zigbee`",
            parse_mode="Markdown",
        )
        return

    user_id = update.effective_user.id
    await update.message.reply_text("🔍 Ищу…", parse_mode="Markdown")

    # Step 1: ILIKE search on text and summary (fast, exact match)
    async with AsyncSessionLocal() as db:
        pattern = f"%{query_text}%"
        stmt = (
            select(Post, Channel.title.label("channel_title"))
            .join(Channel, Post.channel_id == Channel.id)
            .where(Channel.user_id == user_id)
            .where(
                or_(
                    Post.text.ilike(pattern),
                    Post.summary.ilike(pattern),
                )
            )
            .where(Post.is_ad == False)
            .order_by(Post.published_at.desc())
            .limit(5)
        )
        rows = (await db.execute(stmt)).all()

    # Step 2: if ILIKE found nothing, try pgvector semantic search
    if not rows:
        rows = await _semantic_search(user_id, query_text)

    if not rows:
        await update.message.reply_text(
            f"🔍 По запросу *{query_text}* ничего не найдено.",
            parse_mode="Markdown",
        )
        return

    lines = [f"🔍 *Результаты поиска:* «{query_text}»\n"]
    for row in rows:
        channel = row.channel_title or "—"
        summary = (row.summary or row.text or "")[:200]
        date = row.published_at.strftime("%d.%m") if row.published_at else ""
        cat = row.category or "—"
        sim = getattr(row, "similarity", None)
        if sim is not None:
            pct = max(0, min(1, 1 - float(sim)))  # distance → similarity
            bar = "🟩" * int(pct * 10) + "⬜" * (10 - int(pct * 10))
            lines.append(f"• *{channel}* [{cat}]  `{pct:.0%}`\n  {summary}\n  _{date}_\n")
        else:
            lines.append(f"• *{channel}* [{cat}]\n  {summary}\n  _{date}_\n")

    text_out = "\n".join(lines)
    if len(text_out) > 4000:
        text_out = text_out[:4000] + "\n…"

    await update.message.reply_text(text_out, parse_mode="Markdown")


async def _semantic_search(user_id: int, query: str, limit: int = 5) -> list:
    """Fallback: pgvector cosine distance search via embedding + progress bar."""
    try:
        embedding = generate_embedding(query)
    except Exception as e:
        logger.warning("Semantic search embedding failed: %s", e)
        return []

    vec_literal = "[" + ",".join(str(x) for x in embedding) + "]"

    async with AsyncSessionLocal() as db:
        sql = text("""
            SELECT p.id, p.channel_id, p.text, p.published_at, p.summary,
                   p.category, p.is_ad,
                   c.title AS channel_title,
                   p.embedding <=> CAST(:query_vec AS vector) AS similarity
            FROM posts p
            JOIN channels c ON c.id = p.channel_id
            WHERE c.user_id = :user_id
              AND p.is_ad = false
              AND p.embedding IS NOT NULL
            ORDER BY similarity
            LIMIT :lim
        """)
        rows = (await db.execute(
            sql, {"query_vec": vec_literal, "user_id": user_id, "lim": limit}
        )).all()

    return rows
