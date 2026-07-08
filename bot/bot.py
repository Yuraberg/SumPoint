"""Telegram bot entry point."""
import logging

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from app.config import get_settings
from bot.handlers.alerts import manage_alerts
from bot.handlers.channels import (
    add_channel,
    import_channels,
    list_channels,
    remove_channel,
)
from bot.handlers.digest import digest_now, filter_by_category, show_events
from bot.handlers.recent import recent_posts
from bot.handlers.search import search_next_page, search_posts
from bot.handlers.settings import (
    schedule_detail,
    set_hours,
    set_model,
    settings_menu,
    toggle_evening,
    toggle_morning,
)
from bot.handlers.start import help_command, start
from bot.keyboards import WELCOME, main_menu_keyboard

logging.basicConfig(level=logging.INFO)
# httpx logs full request URLs at INFO — suppressed to avoid leaking the bot
# token (embedded in every Telegram Bot API URL) to docker logs / log shippers.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def back_main(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return to the /start main menu."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        WELCOME, parse_mode="Markdown", reply_markup=main_menu_keyboard(with_web_app=False)
    )


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log unhandled handler exceptions so they aren't silently swallowed."""
    logger.exception("Unhandled error while processing update", exc_info=context.error)


def main() -> None:
    settings = get_settings()
    app = Application.builder().token(settings.telegram_bot_token).build()

    app.add_error_handler(on_error)

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
