"""Settings / preferences handlers."""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from app.database import AsyncSessionLocal
from app.models.user import User
from sqlalchemy import select


async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if not user:
            await query.edit_message_text("Пользователь не найден.")
            return
        morning = "✅" if user.digest_morning else "❌"
        evening = "✅" if user.digest_evening else "❌"

    keyboard = [
        [InlineKeyboardButton(f"{morning} Утренний дайджест (08:00)", callback_data="toggle_morning")],
        [InlineKeyboardButton(f"{evening} Вечерний дайджест (20:00)", callback_data="toggle_evening")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_main")],
    ]
    await query.edit_message_text(
        "⚙️ *Настройки дайджеста*\nВыберите, когда получать сводку:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def toggle_morning(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _toggle_digest(update, "morning")


async def toggle_evening(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _toggle_digest(update, "evening")


async def _toggle_digest(update: Update, slot: str) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if not user:
            user = User(id=user_id, first_name=query.from_user.first_name or "")
            db.add(user)
            await db.flush()
        if slot == "morning":
            user.digest_morning = not user.digest_morning
            status = "включён" if user.digest_morning else "отключён"
            label = "утренний"
        else:
            user.digest_evening = not user.digest_evening
            status = "включён" if user.digest_evening else "отключён"
            label = "вечерний"
        await db.commit()

    await query.answer(f"{label.capitalize()} дайджест {status}.", show_alert=True)
    await settings_menu(update, context)
