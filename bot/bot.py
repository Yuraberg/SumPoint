"""Telegram bot entry point."""
import functools
import logging

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.repositories import user_repository
from bot.handlers.access import approve_user_callback, invite_command
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
from bot.handlers.start import (
    PENDING_TEXT,
    help_command,
    maybe_redeem_invite_text,
    start,
)
from bot.keyboards import WELCOME, main_menu_keyboard

logging.basicConfig(level=logging.INFO)
# httpx logs full request URLs at INFO — suppressed to avoid leaking the bot
# token (embedded in every Telegram Bot API URL) to docker logs / log shippers.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def require_approved(handler):
    """Gate a data-touching command/callback behind account approval. Centralised
    here (wrapping registration in main()) rather than duplicated in every
    handler file — /start manages its own pending flow and isn't wrapped;
    /help and /invite are harmless/self-guarded and also aren't wrapped."""
    @functools.wraps(handler)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user:
            return
        owner_ids = get_settings().owner_telegram_id_set
        approved = user.id in owner_ids
        if not approved:
            async with AsyncSessionLocal() as db:
                db_user = await user_repository.get_by_id(db, user.id)
            approved = bool(db_user and db_user.is_approved)
        if not approved:
            if update.callback_query:
                await update.callback_query.answer("Доступ ожидает одобрения владельца.", show_alert=True)
            elif update.effective_message:
                await update.effective_message.reply_text(PENDING_TEXT, parse_mode="Markdown")
            return
        return await handler(update, context)
    return wrapped


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

    # /start manages its own pending/approved branching; /help and /invite are
    # harmless or self-guarded — everything else touches user data and is
    # gated behind approval via require_approved.
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("invite", invite_command))
    app.add_handler(CommandHandler("search", require_approved(search_posts)))
    app.add_handler(CommandHandler("recent", require_approved(recent_posts)))
    app.add_handler(CommandHandler("channels", require_approved(list_channels)))
    app.add_handler(CommandHandler("addchannel", require_approved(add_channel)))
    app.add_handler(CommandHandler("removechannel", require_approved(remove_channel)))
    app.add_handler(CommandHandler("import", require_approved(import_channels)))
    app.add_handler(CommandHandler("alert", require_approved(manage_alerts)))

    app.add_handler(CallbackQueryHandler(approve_user_callback, pattern="^approve_user_"))
    app.add_handler(CallbackQueryHandler(require_approved(digest_now), pattern="^digest_now$"))
    app.add_handler(CallbackQueryHandler(require_approved(show_events), pattern="^events$"))
    app.add_handler(CallbackQueryHandler(require_approved(settings_menu), pattern="^settings$"))
    app.add_handler(CallbackQueryHandler(require_approved(back_main), pattern="^back_main$"))
    app.add_handler(CallbackQueryHandler(require_approved(toggle_morning), pattern="^toggle_morning$"))
    app.add_handler(CallbackQueryHandler(require_approved(toggle_evening), pattern="^toggle_evening$"))
    app.add_handler(CallbackQueryHandler(require_approved(schedule_detail), pattern="^schedule_detail_"))
    app.add_handler(CallbackQueryHandler(require_approved(set_hours), pattern="^set_hours_"))
    app.add_handler(CallbackQueryHandler(require_approved(set_model), pattern="^set_model_"))
    app.add_handler(CallbackQueryHandler(require_approved(filter_by_category), pattern="^filter_"))
    app.add_handler(CallbackQueryHandler(require_approved(search_next_page), pattern="^search_next$"))

    # Pending users can redeem an invite code by typing it as a plain message;
    # no-ops for anyone approved or any text that isn't an 8-hex-char code.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, maybe_redeem_invite_text))

    logger.info("SumPoint bot started.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
