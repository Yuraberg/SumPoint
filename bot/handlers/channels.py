"""/channels, /addchannel, /removechannel — channel management from the bot."""
import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.database import AsyncSessionLocal
from app.models.channel import Channel
from app.repositories import channel_repository
from app.utils.text import truncate

logger = logging.getLogger(__name__)


async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List the user's channels with last fetch status. Usage: /channels"""
    user_id = update.effective_user.id

    async with AsyncSessionLocal() as db:
        rows = await channel_repository.get_for_user_ordered(db, user_id)

    if not rows:
        await update.message.reply_text(
            "📡 У вас пока нет каналов.\n\nДобавить: `/addchannel @username`",
            parse_mode="Markdown",
        )
        return

    lines = ["📡 *Ваши каналы:*\n"]
    for ch in rows:
        status = "⚠️" if ch.last_error else ("✅" if ch.last_fetched_at else "⏳")
        line = f"{status} *{ch.title}* (id `{ch.id}`)"
        if ch.last_error:
            line += f"\n   _ошибка: {ch.last_error[:100]}_"
        lines.append(line)

    lines.append("\nУдалить: `/removechannel <id>`")
    await update.message.reply_text(truncate("\n".join(lines)), parse_mode="Markdown")


async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add a channel by @username. Usage: /addchannel @username"""
    if not context.args:
        await update.message.reply_text(
            "Использование: `/addchannel @username`", parse_mode="Markdown"
        )
        return

    username = context.args[0].lstrip("@")
    user_id = update.effective_user.id
    await update.message.reply_text("⏳ Ищу канал…")

    from app.tasks.maintenance_tasks import resolve_channel_username

    try:
        result = await asyncio.to_thread(
            lambda: resolve_channel_username.apply_async(args=[user_id, username]).get(timeout=30)
        )
    except Exception as e:
        logger.warning("resolve_channel_username failed for %s: %s", username, e)
        await update.message.reply_text(f"⚠️ Не удалось найти канал @{username}: {e}")
        return

    if not result:
        await update.message.reply_text(f"⚠️ Канал @{username} не найден.")
        return

    async with AsyncSessionLocal() as db:
        existing = await channel_repository.get_by_telegram_id(db, user_id, result["telegram_id"])
        if existing:
            await update.message.reply_text(f"Канал *{existing.title}* уже добавлен.", parse_mode="Markdown")
            return

        ch = Channel(
            user_id=user_id,
            telegram_id=result["telegram_id"],
            username=result.get("username") or username,
            title=result.get("title") or username,
        )
        db.add(ch)
        await db.commit()

    await update.message.reply_text(f"✅ Канал *{ch.title}* добавлен.", parse_mode="Markdown")


async def import_channels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Import all subscribed Telegram channels. Usage: /import"""
    user_id = update.effective_user.id
    await update.message.reply_text("⏳ Импортирую ваши каналы из Telegram, это может занять до пары минут…")

    from app.tasks.maintenance_tasks import import_channels_for_user

    task = import_channels_for_user.apply_async(args=[user_id])
    try:
        result = await asyncio.to_thread(lambda: task.get(timeout=120))
    except Exception:
        await update.message.reply_text(
            "⌛ Импорт занимает больше времени, чем обычно — он продолжается в фоне. "
            "Проверьте `/channels` через пару минут.",
            parse_mode="Markdown",
        )
        return

    if result.get("error"):
        await update.message.reply_text(f"⚠️ Ошибка импорта: {result['error']}")
        return

    await update.message.reply_text(
        f"✅ Импортировано {result.get('imported', 0)} из {result.get('total', 0)} каналов."
    )


async def remove_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove a channel by id. Usage: /removechannel <id>"""
    if not context.args:
        await update.message.reply_text(
            "Использование: `/removechannel <id>` (id см. в /channels)", parse_mode="Markdown"
        )
        return

    try:
        channel_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("id должен быть числом.")
        return

    user_id = update.effective_user.id
    async with AsyncSessionLocal() as db:
        ch = await channel_repository.get_owned(db, channel_id, user_id)
        if not ch:
            await update.message.reply_text("Канал не найден.")
            return
        title = ch.title
        await db.delete(ch)
        await db.commit()

    await update.message.reply_text(f"🗑 Канал *{title}* удалён.", parse_mode="Markdown")
