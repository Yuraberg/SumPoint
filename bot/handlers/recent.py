""" /recent command — latest posts without searching, optional #category filter. """
from telegram import Update
from telegram.ext import ContextTypes

from app.database import AsyncSessionLocal
from app.repositories import post_repository
from app.utils.text import truncate

_LIMIT = 5


async def recent_posts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the latest posts. Usage: /recent [#Категория]"""
    category = None
    for arg in context.args or []:
        if arg.startswith("#"):
            category = arg[1:]

    user_id = update.effective_user.id

    async with AsyncSessionLocal() as db:
        rows = await post_repository.get_recent_for_category(
            db, user_id, category, limit=_LIMIT
        )

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

    await update.message.reply_text(truncate("\n".join(lines)), parse_mode="Markdown")
