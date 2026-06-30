"""Settings / schedule preferences handlers."""
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from app.database import AsyncSessionLocal
from app.models.user import User
from app.models.digest_schedule import DigestSchedule, AVAILABLE_MODELS, VALID_HOURS
from sqlalchemy import select

_SLOT_LABELS = {"morning": "🌅 Утренний (09:00)", "evening": "🌆 Вечерний (21:00)"}
_HOURS_LABELS = {24: "24 ч", 72: "72 ч", 168: "7 дней"}
_MODEL_LABELS = {"deepseek-chat": "Flash", "deepseek-reasoner": "Pro"}


async def _load_or_create(db, user_id: int, slot: str) -> DigestSchedule:
    sched = (
        await db.execute(
            select(DigestSchedule).where(
                DigestSchedule.user_id == user_id,
                DigestSchedule.slot == slot,
            )
        )
    ).scalar_one_or_none()
    if sched is None:
        sched = DigestSchedule(user_id=user_id, slot=slot, enabled=(slot == "morning"))
        db.add(sched)
        await db.flush()
        # No commit here — caller commits atomically with all pending changes
    return sched


# ── Main settings menu ────────────────────────────────────────────────────────

async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if not user:
            await query.edit_message_text("Пользователь не найден.")
            return
        morning_on = "✅" if user.digest_morning else "❌"
        evening_on = "✅" if user.digest_evening else "❌"

    keyboard = [
        [InlineKeyboardButton(f"{morning_on} Утренний дайджест (09:00)", callback_data="toggle_morning")],
        [InlineKeyboardButton("⚙️ Настроить утренний", callback_data="schedule_detail_morning")],
        [InlineKeyboardButton(f"{evening_on} Вечерний дайджест (21:00)", callback_data="toggle_evening")],
        [InlineKeyboardButton("⚙️ Настроить вечерний", callback_data="schedule_detail_evening")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_main")],
    ]
    await query.edit_message_text(
        "⚙️ *Настройки дайджеста*\nВыберите расписание или детальные параметры:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ── Toggle morning / evening ──────────────────────────────────────────────────

async def toggle_morning(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _toggle_digest(update, "morning")


async def toggle_evening(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _toggle_digest(update, "evening")


async def _toggle_digest(update: Update, slot: str) -> None:
    query = update.callback_query
    user_id = query.from_user.id

    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if not user:
            user = User(id=user_id, first_name=query.from_user.first_name or "")
            db.add(user)
            await db.flush()
        if slot == "morning":
            user.digest_morning = not user.digest_morning
            flag = user.digest_morning
        else:
            user.digest_evening = not user.digest_evening
            flag = user.digest_evening

        # Sync with DigestSchedule
        sched = await _load_or_create(db, user_id, slot)
        sched.enabled = flag
        sched.updated_at = datetime.utcnow()
        await db.commit()

    status = "включён" if flag else "отключён"
    label = "утренний" if slot == "morning" else "вечерний"
    await query.answer(f"{label.capitalize()} дайджест {status}.", show_alert=True)
    await settings_menu(update, context)


# ── Detail menu for a slot ────────────────────────────────────────────────────

async def schedule_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    slot = query.data.replace("schedule_detail_", "")
    if slot not in _SLOT_LABELS:
        await query.answer("Некорректные данные.", show_alert=True)
        return
    user_id = query.from_user.id

    async with AsyncSessionLocal() as db:
        sched = await _load_or_create(db, user_id, slot)
        cur_hours = sched.hours_back
        cur_model = sched.model

    label = _SLOT_LABELS[slot]
    hours_row = [
        InlineKeyboardButton(
            f"{'✓ ' if h == cur_hours else ''}{_HOURS_LABELS[h]}",
            callback_data=f"set_hours_{slot}_{h}",
        )
        for h in VALID_HOURS
    ]
    model_row = [
        InlineKeyboardButton(
            f"{'✓ ' if m == cur_model else ''}{_MODEL_LABELS[m]}",
            callback_data=f"set_model_{slot}_{m}",
        )
        for m in AVAILABLE_MODELS
    ]
    keyboard = [
        hours_row,
        model_row,
        [InlineKeyboardButton("🔙 Настройки", callback_data="settings")],
    ]
    await query.edit_message_text(
        f"*{label}* — параметры:\n\n"
        f"⏱ *Глубина:* {_HOURS_LABELS.get(cur_hours, str(cur_hours))}\n"
        f"🤖 *Модель:* {_MODEL_LABELS.get(cur_model, cur_model)}\n\n"
        "Выберите параметр для изменения:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ── Set hours_back ────────────────────────────────────────────────────────────

async def set_hours(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    # pattern: set_hours_{slot}_{hours}
    try:
        _, _, slot, hours_str = query.data.split("_", 3)
        hours = int(hours_str)
    except (ValueError, IndexError):
        await query.answer("Некорректные данные.", show_alert=True)
        return
    if slot not in _SLOT_LABELS or hours not in VALID_HOURS:
        await query.answer("Некорректные данные.", show_alert=True)
        return
    user_id = query.from_user.id

    async with AsyncSessionLocal() as db:
        sched = await _load_or_create(db, user_id, slot)
        sched.hours_back = hours
        sched.updated_at = datetime.utcnow()
        await db.commit()

    await query.answer(f"Глубина сбора: {_HOURS_LABELS.get(hours, str(hours))}", show_alert=False)
    # Refresh the detail menu
    query.data = f"schedule_detail_{slot}"
    await schedule_detail(update, context)


# ── Set model ─────────────────────────────────────────────────────────────────

async def set_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    # pattern: set_model_{slot}_{model_name}  (model_name may contain hyphens)
    parts = query.data.split("_", 3)  # ["set", "model", slot, model_name]
    if len(parts) != 4:
        await query.answer("Некорректные данные.", show_alert=True)
        return
    slot, model_name = parts[2], parts[3]
    if slot not in _SLOT_LABELS or model_name not in AVAILABLE_MODELS:
        await query.answer("Некорректные данные.", show_alert=True)
        return
    user_id = query.from_user.id

    async with AsyncSessionLocal() as db:
        sched = await _load_or_create(db, user_id, slot)
        sched.model = model_name
        sched.updated_at = datetime.utcnow()
        await db.commit()

    await query.answer(f"Модель: {_MODEL_LABELS.get(model_name, model_name)}", show_alert=False)
    query.data = f"schedule_detail_{slot}"
    await schedule_detail(update, context)
