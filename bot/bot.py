"""Telegram bot entry point."""
import logging
from telegram.ext import Application, CommandHandler, CallbackQueryHandler

from app.config import get_settings
from bot.handlers.start import start, help_command
from bot.handlers.search import search_posts, search_next_page
from bot.handlers.recent import recent_posts
from bot.handlers.channels import list_channels, add_channel, remove_channel, import_channels
from bot.handlers.alerts import manage_alerts
from bot.handlers.digest import digest_now, filter_by_category, show_events
from bot.handlers.settings import (
    settings_menu, toggle_morning, toggle_evening,
    schedule_detail, set_hours, set_model,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def back_main(update, context):
    """Return to the /start main menu."""
    from bot.handlers.start import WELCOME
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("📋 Дайджест сейчас", callback_data="digest_now")],
        [
            InlineKeyboardButton("🌅 Утренний дайджест", callback_data="toggle_morning"),
            InlineKeyboardButton("🌆 Вечерний дайджест", callback_data="toggle_evening"),
        ],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="settings")],
    ]
    await query.edit_message_text(
        WELCOME, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


def main() -> None:
    settings = get_settings()
    app = Application.builder().token(settings.telegram_bot_token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("search", search_posts))
    app.add_handler(CommandHandler("recent", recent_posts))
    app.add_handler(CommandHandler("channels", list_channels))
    app.add_handler(CommandHandler("addchannel", add_channel))
    app.add_handler(CommandHandler("removechannel", remove_channel))
    app.add_handler(CommandHandler("import", import_channels))
    app.add_handler(CommandHandler("alert", manage_alerts))

    app.add_handler(CallbackQueryHandler(digest_now, pattern="^digest_now$"))
    app.add_handler(CallbackQueryHandler(show_events, pattern="^events$"))
    app.add_handler(CallbackQueryHandler(settings_menu, pattern="^settings$"))
    app.add_handler(CallbackQueryHandler(back_main, pattern="^back_main$"))
    app.add_handler(CallbackQueryHandler(toggle_morning, pattern="^toggle_morning$"))
    app.add_handler(CallbackQueryHandler(toggle_evening, pattern="^toggle_evening$"))
    app.add_handler(CallbackQueryHandler(schedule_detail, pattern="^schedule_detail_"))
    app.add_handler(CallbackQueryHandler(set_hours, pattern="^set_hours_"))
    app.add_handler(CallbackQueryHandler(set_model, pattern="^set_model_"))
    app.add_handler(CallbackQueryHandler(filter_by_category, pattern="^filter_"))
    app.add_handler(CallbackQueryHandler(search_next_page, pattern="^search_next$"))

    logger.info("SumPoint bot started.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
