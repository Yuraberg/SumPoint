""" /favorites command — favorited posts and events, grouped by category,
with numbered buttons to remove them. """
from collections import defaultdict

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.database import AsyncSessionLocal
from app.repositories import favorite_repository
from app.services.calendar_service import get_favorite_events
from app.utils.text import truncate

_MAX_POSTS = 10
_MAX_EVENTS = 10
_EMPTY_TEXT = (
    "⭐ В избранном пока пусто.\n\n"
    "Откройте пост или событие в веб-приложении и нажмите ★, "
    "или используйте кнопки под /recent и /search."
)


def _chunk(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def favorite_toggle_row(items: list[tuple[int, bool]]) -> list[InlineKeyboardButton]:
    """Row of numbered ⭐/☆ toggle buttons, one per (post_id, is_favorite) pair
    in display order — shared by /recent and /search result lists."""
    return [
        InlineKeyboardButton(f"{'⭐' if is_fav else '☆'}{i}", callback_data=f"favtoggle:{post_id}")
        for i, (post_id, is_fav) in enumerate(items, start=1)
    ]


async def _build_favorites_view(
    user_id: int, *, with_back_button: bool = False
) -> tuple[str, InlineKeyboardMarkup | None]:
    """Fetch favorited posts/events and render the (text, keyboard) pair
    shared by the /favorites command and the toggle-button refresh.
    ``with_back_button`` adds a "🔙 Назад" row back to the /start main menu —
    used when this view was opened from there rather than via /favorites."""
    async with AsyncSessionLocal() as db:
        post_rows = (await favorite_repository.list_favorite_posts(db, user_id))[:_MAX_POSTS]
        events = (await get_favorite_events(db, user_id))[:_MAX_EVENTS]

    if not post_rows and not events:
        if with_back_button:
            return _EMPTY_TEXT, InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]])
        return _EMPTY_TEXT, None

    lines = ["⭐ *Избранное*\n"]
    post_buttons = []
    if post_rows:
        lines.append("*Посты:*")
        by_category = defaultdict(list)
        for row in post_rows:
            by_category[row.Post.category or "Прочее"].append(row)
        for category, rows in by_category.items():
            lines.append(f"\n_{category}_")
            for row in rows:
                n = len(post_buttons) + 1
                channel = row.channel_title or "—"
                summary = (row.Post.summary or row.Post.text or "")[:150]
                lines.append(f"{n}. *{channel}*\n   {summary}")
                post_buttons.append(
                    InlineKeyboardButton(f"✖ {n}", callback_data=f"favtoggle:{row.Post.id}")
                )

    event_buttons = []
    if events:
        lines.append("\n*События:*")
        for ev in events:
            n = len(event_buttons) + 1
            name = ev.get("name") or "Событие"
            date = ev.get("date") or ""
            lines.append(f"{n}. *{name}* — {date}")
            event_buttons.append(
                InlineKeyboardButton(
                    f"✖ {n}", callback_data=f"favtoggleev:{ev['post_id']}:{ev['event_index']}"
                )
            )

    rows_kb = []
    if post_buttons:
        rows_kb.extend(_chunk(post_buttons, 5))
    if event_buttons:
        rows_kb.extend(_chunk(event_buttons, 5))
    if with_back_button:
        rows_kb.append([InlineKeyboardButton("🔙 Назад", callback_data="back_main")])

    text = truncate("\n".join(lines))
    return text, InlineKeyboardMarkup(rows_kb) if rows_kb else None


async def list_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/favorites — show favorited posts and events, grouped by category."""
    text, keyboard = await _build_favorites_view(update.effective_user.id)
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def favorites_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """"⭐ Избранное" button on the /start main menu."""
    query = update.callback_query
    await query.answer()
    text, keyboard = await _build_favorites_view(query.from_user.id, with_back_button=True)
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def _refresh_if_favorites_view(query) -> None:
    """After a toggle from within a favorites message, re-render it in place —
    preserving the "🔙 Назад" row if this view was opened from the main menu.
    No-op if the button was pressed under /recent or /search instead; those
    messages keep their own content and just get the toast."""
    if not (query.message and query.message.text and query.message.text.startswith("⭐ *Избранное*")):
        return
    had_back_button = any(
        btn.callback_data == "back_main"
        for row in (query.message.reply_markup.inline_keyboard if query.message.reply_markup else [])
        for btn in row
    )
    text, keyboard = await _build_favorites_view(query.from_user.id, with_back_button=had_back_button)
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def toggle_favorite_post_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """✖N / ⭐N button — toggles a post's favorite state."""
    query = update.callback_query
    post_id = int(query.data.split(":", 1)[1])
    user_id = query.from_user.id

    async with AsyncSessionLocal() as db:
        try:
            is_favorite = await favorite_repository.toggle(db, user_id, post_id)
        except LookupError:
            await query.answer("Пост не найден.", show_alert=True)
            return

    await query.answer("Добавлено в избранное ⭐" if is_favorite else "Убрано из избранного")
    await _refresh_if_favorites_view(query)


async def toggle_favorite_event_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """✖N button under a favorited event."""
    query = update.callback_query
    _, post_id, event_index = query.data.split(":")
    user_id = query.from_user.id

    async with AsyncSessionLocal() as db:
        try:
            is_favorite = await favorite_repository.toggle(db, user_id, int(post_id), int(event_index))
        except LookupError:
            await query.answer("Событие не найдено.", show_alert=True)
            return

    await query.answer("Добавлено в избранное ⭐" if is_favorite else "Убрано из избранного")
    await _refresh_if_favorites_view(query)
