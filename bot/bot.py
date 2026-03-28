"""Telegram bot entry point."""
import logging
from telegram.ext import Application, CommandHandler, CallbackQueryHandler

from app.config import get_settings
from bot.handlers.start import start
from bot.handlers.digest import digest_now, filter_by_category, show_events
from bot.handlers.settings import settings_menu, toggle_morning, toggle_evening

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    settings = get_settings()
    app = Application.builder().token(settings.telegram_bot_token).build()

    # Commands
    app.add_handler(CommandHandler("start", start))

    # Callback queries
    app.add_handler(CallbackQueryHandler(digest_now, pattern="^digest_now$"))
    app.add_handler(CallbackQueryHandler(show_events, pattern="^events$"))
    app.add_handler(CallbackQueryHandler(settings_menu, pattern="^settings$"))
    app.add_handler(CallbackQueryHandler(toggle_morning, pattern="^toggle_morning$"))
    app.add_handler(CallbackQueryHandler(toggle_evening, pattern="^toggle_evening$"))
    app.add_handler(CallbackQueryHandler(filter_by_category, pattern="^filter_"))

    logger.info("SumPoint bot started.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
