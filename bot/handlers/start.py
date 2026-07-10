""" /start command handler — saves chat_id for Magic Link login, and gates
access: a brand-new user is approved only via the owner allowlist or a valid
invite code (deep-link t.me/<bot>?start=<code>, or typed as a plain message
by a pending user).
"""
import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.repositories import invite_repository, user_repository
from bot.keyboards import (  # noqa: F401  (WELCOME re-exported)
    WELCOME,
    main_menu_keyboard,
)

logger = logging.getLogger(__name__)

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

PENDING_TEXT = (
    "⏳ *Заявка отправлена*\n\n"
    "Ваш аккаунт создан, но доступ пока не подтверждён владельцем сервиса.\n"
    "Если у вас есть код-приглашение, отправьте его сообщением боту — "
    "он тоже даёт мгновенный доступ."
)

# Matches an invite code on its own in a message, e.g. "AB12CD34" — codes are
# 8 uppercase hex chars (see app/models/invite_code.py:_gen_code).
_CODE_RE = re.compile(r"^[0-9A-F]{8}$")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Greet user and save chat_id for future Magic Link logins. A deep-link
    invite code (t.me/<bot>?start=<code>) auto-approves a brand-new signup."""
    user = update.effective_user
    if not user:
        return

    invite_code = context.args[0] if context.args else None
    is_new, approved = await _save_chat_id(
        user.id, user.username, user.first_name, user.last_name,
        update.effective_chat.id, invite_code,
    )

    if is_new and not approved:
        await _notify_owners_pending(context, user.id, user.username, user.first_name)
        await update.message.reply_text(PENDING_TEXT, parse_mode="Markdown")
        return

    await update.message.reply_text(
        WELCOME,
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(with_web_app=True),
    )


async def maybe_redeem_invite_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A plain-text message that looks like an invite code, from a user who is
    still pending approval, redeems it. Registered as a low-priority text
    handler so it never shadows the bot's other free-text flows."""
    msg = update.message
    user = update.effective_user
    if not msg or not msg.text or not user:
        return
    code = msg.text.strip().upper()
    if not _CODE_RE.match(code):
        return

    async with AsyncSessionLocal() as db:
        db_user = await user_repository.get_by_id(db, user.id)
        if db_user is None or db_user.is_approved:
            return  # not our concern — no pending account to approve here
        if await invite_repository.try_consume(db, code):
            db_user.is_approved = True
            await db.commit()
            await msg.reply_text(
                "✅ Код принят, доступ открыт! Нажмите /start, чтобы продолжить."
            )
        else:
            await msg.reply_text("❌ Код недействителен или уже использован.")


async def _save_chat_id(
    user_id: int, username: str | None, first_name: str, last_name: str | None,
    chat_id: int, invite_code: str | None,
) -> tuple[bool, bool]:
    """Save or update user's chat_id for Magic Link delivery. Returns
    (is_new_signup, is_approved)."""
    async with AsyncSessionLocal() as db:
        existing = await user_repository.get_by_id(db, user_id)
        is_new = existing is None
        saved = await user_repository.login_or_signup(
            db, user_id,
            first_name=first_name, last_name=last_name,
            username=username, chat_id=chat_id, invite_code=invite_code,
        )
        await db.commit()
        owner_ids = get_settings().owner_telegram_id_set
        approved = saved.is_approved or saved.id in owner_ids
        return is_new, approved


async def _notify_owners_pending(
    context: ContextTypes.DEFAULT_TYPE, user_id: int, username: str | None, first_name: str,
) -> None:
    """DM every configured owner with an inline "Одобрить" button so approving
    a new pending user takes one tap, no admin panel needed."""
    owner_ids = get_settings().owner_telegram_id_set
    if not owner_ids:
        return
    who = f"@{username}" if username else first_name
    text = f"🆕 Новая заявка на доступ: {who} (id `{user_id}`), без кода-приглашения."
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_user_{user_id}"),
    ]])
    for owner_id in owner_ids:
        try:
            await context.bot.send_message(
                chat_id=owner_id, text=text, parse_mode="Markdown", reply_markup=keyboard,
            )
        except Exception:
            logger.warning("Failed to notify owner %s about pending user %s", owner_id, user_id)
