""" /start command handler — saves chat_id for Magic Link login. """
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ContextTypes
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.user import User


WELCOME = (
    "👋 *Добро пожаловать в SumPoint!*\n\n"
    "Я собираю посты из ваших Telegram-каналов и превращаю их в краткий ежедневный дайджест.\n\n"
    "Что умею:\n"
    "• 📰 Краткое резюме каждого поста\n"
    "• 🏷 Классификация по темам (Рынок, Технологии, События…)\n"
    "• 📅 Автоматический календарь событий\n"
    "• 🔍 Поиск: `/search умный дом`\n"
    "• 🏷 Тематический поиск\n\n"
    "Используйте кнопки ниже для управления.\n"
    "Или нажмите *🌐 Веб-приложение*, чтобы открыть SumPoint в Telegram."
)


HELP_TEXT = (
    "🛟 *Команды SumPoint*\n\n"
    "*Посты*\n"
    "• `/recent` — последние посты\n"
    "• `/recent #Категория` — последние посты по теме\n"
    "• `/search <текст>` — поиск по постам\n"
    "• `/search <текст> #Категория` — поиск с фильтром по теме\n\n"
    "*Каналы*\n"
    "• `/channels` — список ваших каналов и их статус\n"
    "• `/addchannel @username` — добавить канал\n"
    "• `/removechannel <id>` — удалить канал\n"
    "• `/import` — импортировать все подписки из Telegram\n\n"
    "*Алерты*\n"
    "• `/alert add <слово>` — уведомлять о новых постах со словом\n"
    "• `/alert remove <слово>` — удалить алерт\n"
    "• `/alert list` — список алертов\n\n"
    "*Прочее*\n"
    "• `/start` — главное меню\n"
    "• `/help` — это сообщение"
)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Greet user and save chat_id for future Magic Link logins."""
    user = update.effective_user
    if user:
        await _save_chat_id(user.id, user.username, user.first_name, user.last_name, update.effective_chat.id)

    keyboard = [
        [InlineKeyboardButton("📋 Дайджест сейчас", callback_data="digest_now")],
        [
            InlineKeyboardButton("🌅 Утренний дайджест", callback_data="toggle_morning"),
            InlineKeyboardButton("🌆 Вечерний дайджест", callback_data="toggle_evening"),
        ],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="settings")],
        [
            InlineKeyboardButton(
                "🌐 Веб-приложение",
                web_app=WebAppInfo(url=get_settings().app_base_url),
            )
        ],
    ]
    await update.message.reply_text(
        WELCOME,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _save_chat_id(user_id: int, username: str | None, first_name: str, last_name: str | None, chat_id: int):
    """Save or update user's chat_id for Magic Link delivery."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            user.chat_id = chat_id
            if username:
                user.username = username
        else:
            db.add(User(
                id=user_id,
                username=username,
                first_name=first_name or "User",
                last_name=last_name,
                chat_id=chat_id,
            ))
        await db.commit()
