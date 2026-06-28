""" /recent command — latest posts without searching, optional #category filter. """
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.post import Post
from app.models.channel import Channel

_LIMIT = 5


async def recent_posts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the latest posts. Usage: /recent [#Категория]"""
    category = None
    for arg in context.args or []:
        if arg.startswith("#"):
            category = arg[1:]

    user_id = update.effective_user.id

    async with AsyncSessionLocal() as db:
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
            .where(Post.is_ad == False)   # noqa: E712
        )
        if category:
            stmt = stmt.where(Post.category == category)
        stmt = stmt.order_by(Post.published_at.desc()).limit(_LIMIT)
        rows = (await db.execute(stmt)).all()

    if not rows:
        msg = "Нет постов." if not category else f"Нет постов в категории *{category}*."
        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    title = "🆕 *Последние посты:*" if not category else f"🆕 *Последние посты* [{category}]:"
    lines = [title + "\n"]
    for row in rows:
        channel = row.channel_title or "—"
        summary = (row.summary or row.text or "")[:200]
        date = row.published_at.strftime("%d.%m %H:%M") if row.published_at else ""
        cat = row.category or "—"
        lines.append(f"• *{channel}* [{cat}]\n  {summary}\n  _{date}_\n")

    text_out = "\n".join(lines)
    if len(text_out) > 4000:
        text_out = text_out[:4000] + "\n…"

    await update.message.reply_text(text_out, parse_mode="Markdown")
