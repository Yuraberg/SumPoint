""" /search command — semantic and ILIKE search over posts. """

import logging
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select, or_

from app.database import AsyncSessionLocal
from app.models.post import Post
from app.models.channel import Channel

logger = logging.getLogger(__name__)

async def search_posts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Search posts by query string. Usage: /search <text>"""
    query_text = " ".join(context.args) if context.args else ""
    if not query_text:
        await update.message.reply_text(
            "🔍 *Поиск*\n\nНапишите запрос после /search:\n`/search умный дом zigbee`",
            parse_mode="Markdown",
        )
        return

    user_id = update.effective_user.id
    async with AsyncSessionLocal() as db:
        # ILIKE search on text and summary
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

    if not rows:
        await update.message.reply_text(
            f"🔍 По запросу *{query_text}* ничего не найдено.",
            parse_mode="Markdown",
        )
        return

    lines = [f"🔍 *Результаты поиска:* «{query_text}»\n"]
    for row in rows:
        post = row.Post
        channel = row.channel_title
        summary = (post.summary or post.text or "")[:200]
        date = post.published_at.strftime("%d.%m") if post.published_at else ""
        cat = post.category or "—"
        lines.append(f"• *{channel}* [{cat}]\n  {summary}\n  _{date}_\n")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n…"

    await update.message.reply_text(text, parse_mode="Markdown")
