"""/alert command — manage keyword alerts, triggered when a new matching post arrives."""
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import AsyncSessionLocal
from app.models.keyword_alert import KeywordAlert

_MAX_ALERTS = 20


async def manage_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manage keyword alerts. Usage: /alert add|remove|list [слово]"""
    args = list(context.args or [])
    user_id = update.effective_user.id

    if not args or args[0] not in ("add", "remove", "list"):
        await update.message.reply_text(
            "🔔 *Алерты по ключевым словам*\n\n"
            "`/alert add <слово>` — уведомлять при новом посте со словом\n"
            "`/alert remove <слово>` — удалить алерт\n"
            "`/alert list` — список алертов",
            parse_mode="Markdown",
        )
        return

    action = args[0]

    if action == "list":
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    select(KeywordAlert).where(KeywordAlert.user_id == user_id).order_by(KeywordAlert.keyword)
                )
            ).scalars().all()
        if not rows:
            await update.message.reply_text("🔔 У вас нет активных алертов.")
            return
        lines = ["🔔 *Ваши алерты:*\n"] + [f"• {row.keyword}" for row in rows]
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    keyword = " ".join(args[1:]).strip().lower()
    if not keyword:
        await update.message.reply_text(f"Использование: `/alert {action} <слово>`", parse_mode="Markdown")
        return

    if action == "add":
        async with AsyncSessionLocal() as db:
            count = len(
                (await db.execute(select(KeywordAlert).where(KeywordAlert.user_id == user_id))).scalars().all()
            )
            if count >= _MAX_ALERTS:
                await update.message.reply_text(f"⚠️ Лимит алертов — {_MAX_ALERTS}.")
                return
            db.add(KeywordAlert(user_id=user_id, keyword=keyword))
            try:
                await db.commit()
            except IntegrityError:
                await update.message.reply_text(f"Алерт «{keyword}» уже есть.")
                return
        await update.message.reply_text(f"✅ Алерт «{keyword}» добавлен.")
        return

    if action == "remove":
        async with AsyncSessionLocal() as db:
            alert = (
                await db.execute(
                    select(KeywordAlert).where(
                        KeywordAlert.user_id == user_id, KeywordAlert.keyword == keyword
                    )
                )
            ).scalar_one_or_none()
            if not alert:
                await update.message.reply_text(f"Алерт «{keyword}» не найден.")
                return
            await db.delete(alert)
            await db.commit()
        await update.message.reply_text(f"🗑 Алерт «{keyword}» удалён.")
