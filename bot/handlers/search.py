""" /search command — semantic search over posts using pgvector + BGE-M3. """

import logging
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import text

from app.database import AsyncSessionLocal
from app.services.ai_engine import generate_embedding

logger = logging.getLogger(__name__)


async def search_posts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Semantic search posts by query. Usage: /search <text>"""
    query_text = " ".join(context.args) if context.args else ""
    if not query_text:
        await update.message.reply_text(
            "🔍 *Поиск*\\n\\nНапишите запрос после /search:\\n`/search умный дом zigbee`",
            parse_mode="Markdown",
        )
        return

    user_id = update.effective_user.id
    await update.message.reply_text("🔍 Ищу…", parse_mode="Markdown")

    # Generate embedding via Ollama BGE-M3
    try:
        embedding = generate_embedding(query_text)
    except Exception as e:
        logger.error("Embedding failed: %s", e)
        await update.message.reply_text("❌ Ошибка генерации эмбеддинга. Попробуйте позже.")
        return

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
            LIMIT 5
        """)
        rows = (await db.execute(sql, {"query_vec": vec_literal, "user_id": user_id})).all()

    if not rows:
        await update.message.reply_text(
            f"🔍 По запросу *{query_text}* ничего не найдено.",
            parse_mode="Markdown",
        )
        return

    lines = [f"🔍 *Результаты поиска:* «{query_text}»\\n"]
    for row in rows:
        channel = row.channel_title or "—"
        summary = (row.summary or row.text or "")[:200]
        date = row.published_at.strftime("%d.%m") if row.published_at else ""
        cat = row.category or "—"
        sim = 1 - float(row.similarity)  # cosine distance → similarity (1 = perfect)
        bar = "🟩" * int(sim * 10) + "⬜" * (10 - int(sim * 10))
        lines.append(f"• *{channel}* [{cat}]  `{sim:.0%}`\\n  {summary}\\n  _{date}_\\n")

    text_out = "\\n".join(lines)
    if len(text_out) > 4000:
        text_out = text_out[:4000] + "\\n…"

    await update.message.reply_text(text_out, parse_mode="Markdown")
