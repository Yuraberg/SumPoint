"""Owner-only access control: generate invite codes, approve pending users."""
import contextlib

from telegram import Update
from telegram.ext import ContextTypes

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.repositories import invite_repository, user_repository


def _is_owner(user_id: int) -> bool:
    return user_id in get_settings().owner_telegram_id_set


async def invite_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/invite — owner only. Generates a single-use invite code and a
    ready-to-share deep link that auto-approves whoever opens it."""
    user = update.effective_user
    if not user or not _is_owner(user.id):
        await update.message.reply_text("Эта команда доступна только владельцу сервиса.")
        return

    async with AsyncSessionLocal() as db:
        invite = await invite_repository.create(db, created_by=user.id)
        await db.commit()
        code = invite.code

    bot_username = (await context.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start={code}"
    await update.message.reply_text(
        f"🎟 Код-приглашение: `{code}`\n\n"
        f"Ссылка (открыть = сразу вход): {link}\n\n"
        f"Разовый — сработает один раз для того, кто им воспользуется первым.",
        parse_mode="Markdown",
    )


async def approve_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inline "✅ Одобрить" button on the owner's pending-signup notification."""
    query = update.callback_query
    actor = update.effective_user
    if not actor or not _is_owner(actor.id):
        await query.answer("Только владелец может одобрять заявки.", show_alert=True)
        return

    target_id = int(query.data.removeprefix("approve_user_"))
    async with AsyncSessionLocal() as db:
        target = await user_repository.get_by_id(db, target_id)
        if target is None:
            await query.answer("Пользователь не найден.", show_alert=True)
            return
        target.is_approved = True
        await db.commit()
        chat_id = target.chat_id
        name = f"@{target.username}" if target.username else target.first_name

    await query.answer("Одобрено")
    await query.edit_message_text(f"✅ Одобрено: {name}")

    if chat_id:
        # Best-effort notification — approval itself already succeeded above.
        with contextlib.suppress(Exception):
            await context.bot.send_message(
                chat_id=chat_id,
                text="✅ Ваш доступ к SumPoint подтверждён владельцем. Нажмите /start, чтобы продолжить.",
            )
