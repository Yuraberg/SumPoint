""" /start command handler. """
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ContextTypes


WELCOME = (
    "👋 *Добро пожаловать в SumPoint!*\n\n"
    "Я собираю посты из ваших Telegram-каналов и превращаю их в краткий ежедневный дайджест.\n\n"
    "Что умею:\n"
    "• 📰 Краткое резюме каждого поста\n"
    "• 🏷 Классификация по темам (Рынок, Технологии, События…)\n"
    "• 📅 Автоматический календарь событий\n"
    "• 🔍 Тематический поиск\n\n"
    "Используйте кнопки ниже для управления.\n"
    "Или нажмите *🌐 Веб-приложение*, чтобы открыть SumPoint в Telegram."
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
                web_app=WebAppInfo(url="https://sum.procpoint.ru"),
            )
        ],
    ]
    await update.message.reply_text(
        WELCOME,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
