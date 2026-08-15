"""Digest-related bot handlers."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.constants import DEFAULT_DIGEST_HOURS
from app.database import AsyncSessionLocal
from app.prompts.classification import CATEGORIES
from app.repositories import post_repository, schedule_repository
from app.services.calendar_service import get_upcoming_events
from app.services.digest_delivery import format_events_message
from app.services.digest_service import build_user_digest
from app.utils.telegram_safe import safe_edit, safe_send
from app.utils.text import split_for_telegram, truncate


async def digest_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the user their digest on demand using their saved schedule preferences."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("⏳ Генерирую дайджест…")

    user_id = query.from_user.id
    async with AsyncSessionLocal() as db:
        sched = await schedule_repository.get_digest_slot(db, user_id, "morning")
        hours = sched.hours_back if sched else DEFAULT_DIGEST_HOURS
        categories = sched.categories if (sched and sched.categories) else None
        model = sched.model if sched else None

        try:
            digest = await build_user_digest(db, user_id, hours=hours, categories=categories, model=model)
        except Exception:
            await query.edit_message_text(
                "⚠️ Не удалось сформировать дайджест — сбой на стороне AI. Попробуйте ещё раз через пару минут."
            )
            return

    text = digest.get("digest_markdown") or f"Нет новых постов за последние {hours} ч."
    parts = split_for_telegram(text) or [text]
    total = len(parts)

    buttons = [[InlineKeyboardButton(cat, callback_data=f"filter_{cat}")] for cat in CATEGORIES[:5]]
    buttons.append([InlineKeyboardButton("📅 События", callback_data="events")])

    for i, part in enumerate(parts):
        body = f"{part}\n\n_Часть {i + 1}/{total}_" if total > 1 else part
        is_last = i == total - 1
        markup = InlineKeyboardMarkup(buttons) if is_last else None
        if i == 0:
            await safe_edit(query, body, reply_markup=markup)
        else:
            await safe_send(context.bot, user_id, body, reply_markup=markup)


async def filter_by_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show posts filtered by a category."""
    query = update.callback_query
    await query.answer()
    category = query.data.replace("filter_", "")

    user_id = query.from_user.id
    async with AsyncSessionLocal() as db:
        rows = await post_repository.get_recent_for_category(db, user_id, category, limit=5)

    if not rows:
        await query.edit_message_text(f"Нет постов в категории *{category}*.", parse_mode="Markdown")
        return

    lines = [f"*{category}* — последние посты:\n"]
    for row in rows:
        lines.append(f"• {row.summary or (row.text or '')[:100]}…")
    await safe_edit(query, truncate("\n".join(lines)))


async def show_events(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show upcoming calendar events."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    async with AsyncSessionLocal() as db:
        events = await get_upcoming_events(db, user_id)

    await safe_edit(query, truncate(format_events_message(events)))
