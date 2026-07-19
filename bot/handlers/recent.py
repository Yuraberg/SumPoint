""" /recent command — latest posts without searching, optional #category filter. """
from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.database import AsyncSessionLocal
from app.repositories import favorite_repository, post_repository
from app.utils.text import truncate
from bot.handlers.favorites import favorite_toggle_row

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
        favorite_ids = await favorite_repository.get_favorite_post_ids(
            db, user_id, [row.id for row in rows]
        )

    if not rows:
        msg = "Нет постов." if not category else f"Нет постов в категории *{category}*."
        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    title = "🆕 *Последние посты:*" if not category else f"🆕 *Последние посты* [{category}]:"
    lines = [title + "\n"]
    for i, row in enumerate(rows, start=1):
        channel = row.channel_title or "—"
        summary = (row.summary or row.text or "")[:200]
        date = row.published_at.strftime("%d.%m %H:%M") if row.published_at else ""
        cat = row.category or "—"
        lines.append(f"{i}. *{channel}* [{cat}]\n  {summary}\n  _{date}_\n")

    keyboard = favorite_toggle_row([(row.id, row.id in favorite_ids) for row in rows])
    await update.message.reply_text(
        truncate("\n".join(lines)), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([keyboard]) if keyboard else None,
    )
