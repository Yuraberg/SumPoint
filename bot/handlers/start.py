""" /start command handler — saves chat_id for Magic Link login. """
from telegram import Update
from telegram.ext import ContextTypes

from app.database import AsyncSessionLocal
from app.repositories import user_repository
from bot.keyboards import WELCOME, main_menu_keyboard  # noqa: F401  (WELCOME re-exported)


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

    await update.message.reply_text(
        WELCOME,
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(with_web_app=True),
    )


async def _save_chat_id(user_id: int, username: str | None, first_name: str, last_name: str | None, chat_id: int):
    """Save or update user's chat_id for Magic Link delivery."""
    async with AsyncSessionLocal() as db:
        await user_repository.get_or_create(
            db, user_id,
            first_name=first_name, last_name=last_name,
            username=username, chat_id=chat_id,
        )
        await db.commit()
