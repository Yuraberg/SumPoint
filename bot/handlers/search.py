""" /search command — ILIKE + pgvector semantic search over posts. """

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select, or_, text

from app.database import AsyncSessionLocal
from app.models.post import Post
from app.models.channel import Channel
from app.api.posts import _escape_like
from app.services.ai_engine import generate_embedding

logger = logging.getLogger(__name__)

_PAGE_SIZE = 5


async def search_posts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Search posts by query. Usage: /search <text> [#Категория]"""
    args = list(context.args or [])
    category = None
    for arg in list(args):
        if arg.startswith("#"):
            category = arg[1:]
            args.remove(arg)
    query_text = " ".join(args)

    if not query_text:
        await update.message.reply_text(
            "🔍 *Поиск*\n\nНапишите запрос после /search:\n"
            "`/search умный дом zigbee`\n"
            "`/search zigbee #Технологии` — с фильтром по категории",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text("🔍 Ищу…", parse_mode="Markdown")
    await _run_search(update.effective_user.id, query_text, category, offset=0, context=context, message=update.message)


async def search_next_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inline 'Ещё' button — show the next page of the last search."""
    query = update.callback_query
    await query.answer()

    state = context.user_data.get("search_state")
    if not state:
        await query.message.reply_text("Поиск устарел, начните новый: `/search <текст>`", parse_mode="Markdown")
        return

    await _run_search(
        update.effective_user.id,
        state["query_text"],
        state["category"],
        offset=state["offset"] + _PAGE_SIZE,
        context=context,
        message=query.message,
    )


async def _run_search(user_id: int, query_text: str, category: str | None, offset: int, context: ContextTypes.DEFAULT_TYPE, message) -> None:
    try:
        # Step 1: ILIKE search on text and summary (fast, exact match)
        async with AsyncSessionLocal() as db:
            pattern = f"%{_escape_like(query_text)}%"
            stmt = (
                select(
                    Post.text,
                    Post.summary,
                    Post.published_at,
                    Post.category,
                    Channel.title.label("channel_title"),
                )
                .join(Channel, Post.channel_id == Channel.id)
                .where(Channel.user_id == user_id)
                .where(
                    or_(
                        Post.text.ilike(pattern),
                        Post.summary.ilike(pattern),
                    )
                )
                .where(Post.is_ad == False)
            )
            if category:
                stmt = stmt.where(Post.category == category)
            stmt = stmt.order_by(Post.published_at.desc()).limit(_PAGE_SIZE).offset(offset)
            rows = (await db.execute(stmt)).all()

        # Step 2: if ILIKE found nothing (only on the first page), try pgvector semantic search
        if not rows and offset == 0:
            rows = await _semantic_search(user_id, query_text)
    except Exception:
        logger.exception("Search failed for query %r", query_text)
        await message.reply_text("⚠️ Ошибка поиска. Попробуйте позже.")
        return

    if not rows:
        text_out = (
            f"🔍 По запросу *{query_text}* больше ничего не найдено."
            if offset > 0
            else f"🔍 По запросу *{query_text}* ничего не найдено."
        )
        await message.reply_text(text_out, parse_mode="Markdown")
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
            lines.append(f"• *{channel}* [{cat}]  `{pct:.0%}`\n  {summary}\n  _{date}_\n")
        else:
            lines.append(f"• *{channel}* [{cat}]\n  {summary}\n  _{date}_\n")

    text_out = "\n".join(lines)
    if len(text_out) > 4000:
        text_out = text_out[:4000] + "\n…"

    context.user_data["search_state"] = {"query_text": query_text, "category": category, "offset": offset}
    reply_markup = None
    if len(rows) == _PAGE_SIZE:
        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("▶️ Ещё", callback_data="search_next")]])

    await message.reply_text(text_out, parse_mode="Markdown", reply_markup=reply_markup)


async def _semantic_search(user_id: int, query: str, limit: int = _PAGE_SIZE) -> list:
    """Fallback: pgvector cosine distance search via embedding."""
    try:
        embedding = await generate_embedding(query)
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
