"""Shared bot text and keyboard layouts.

The main menu used to be defined twice — in ``bot/bot.py`` (back_main) and in
``bot/handlers/start.py`` (start). Both now import from here so the layout can't
drift between the two entry points.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from app.config import get_settings

WELCOME = (
    "👋 *Добро пожаловать в SumPoint!*\n\n"
    "Я собираю посты из ваших Telegram-каналов и превращаю их в краткий ежедневный дайджест.\n\n"
    "Что умею:\n"
    "• 📰 Краткое резюме каждого поста\n"
    "• 🏷 Классификация по темам (Рынок, Технологии, События…)\n"
    "• 📅 Автоматический календарь событий\n"
    "• 🔍 Поиск: `/search умный дом`\n"
    "• 🏷 Тематический поиск\n"
    "• 🔔 Алерты по словам: `/alert add zigbee`\n"
    "• 🗞 Последние посты: `/recent`\n"
    "• 📡 Каналы: `/channels`, `/addchannel @username`\n\n"
    "Используйте кнопки ниже для управления.\n"
    "Или нажмите *🌐 Веб-приложение*, чтобы открыть SumPoint в Telegram.\n\n"
    "Полный список команд — `/help`."
)


def main_menu_keyboard(*, with_web_app: bool = True) -> InlineKeyboardMarkup:
    """Build the primary inline menu. ``with_web_app`` adds the Mini App button
    (only shown from /start, where the message isn't being edited in place)."""
    keyboard = [
        [InlineKeyboardButton("📋 Дайджест сейчас", callback_data="digest_now")],
        [
            InlineKeyboardButton("🌅 Утренний дайджест", callback_data="toggle_morning"),
            InlineKeyboardButton("🌆 Вечерний дайджест", callback_data="toggle_evening"),
        ],
        [InlineKeyboardButton("⭐ Избранное", callback_data="favorites_menu")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="settings")],
    ]
    if with_web_app:
        keyboard.append([
            InlineKeyboardButton(
                "🌐 Веб-приложение",
                web_app=WebAppInfo(url=get_settings().app_base_url),
            )
        ])
    return InlineKeyboardMarkup(keyboard)
