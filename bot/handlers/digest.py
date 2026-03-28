"""Digest-related bot handlers."""
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from app.database import AsyncSessionLocal
from app.services.digest_service import build_user_digest
from app.prompts.classification import CATEGORIES


async def digest_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the user their digest on demand."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("⏳ Генерирую дайджест…")

    user_id = query.from_user.id
    async with AsyncSessionLocal() as db:
        digest = await build_user_digest(db, user_id)

    text = digest.get("digest_markdown") or "Нет новых постов за последние 24 часа."
    # Telegram messages are max 4096 chars
    if len(text) > 4000:
        text = text[:4000] + "\n…"

    # Category filter buttons
    buttons = [[InlineKeyboardButton(cat, callback_data=f"filter_{cat}")] for cat in CATEGORIES[:5]]
    buttons.append([InlineKeyboardButton("📅 События", callback_data="events")])

    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def filter_by_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show posts filtered by a category."""
    query = update.callback_query
    await query.answer()
    category = query.data.replace("filter_", "")

    user_id = query.from_user.id
    async with AsyncSessionLocal() as db:
        from app.models.post import Post
        from app.models.channel import Channel
        from sqlalchemy import select

        stmt = (
            select(Post)
            .join(Channel, Post.channel_id == Channel.id)
            .where(Channel.user_id == user_id)
            .where(Post.category == category)
            .where(Post.is_ad == False)   # noqa: E712
            .order_by(Post.published_at.desc())
            .limit(5)
        )
        posts = (await db.execute(stmt)).scalars().all()

    if not posts:
        await query.edit_message_text(f"Нет постов в категории *{category}*.", parse_mode="Markdown")
        return

    lines = [f"*{category}* — последние посты:\n"]
    for p in posts:
        lines.append(f"• {p.summary or (p.text or '')[:100]}…")
    await query.edit_message_text("\n".join(lines), parse_mode="Markdown")


async def show_events(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show upcoming calendar events."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    async with AsyncSessionLocal() as db:
        from app.services.calendar_service import get_upcoming_events
        events = await get_upcoming_events(db, user_id)

    if not events:
        await query.edit_message_text("📅 Нет предстоящих событий на ближайшие 7 дней.")
        return

    lines = ["📅 *Предстоящие события:*\n"]
    for ev in events:
        date = ev.get("date") or "дата не указана"
        time_ = ev.get("time") or ""
        name = ev.get("name") or "Без названия"
        link = ev.get("link") or ""
        line = f"• *{name}* — {date} {time_}"
        if link:
            line += f" [→]({link})"
        lines.append(line)

    await query.edit_message_text("\n".join(lines), parse_mode="Markdown")
