"""Digest / event message assembly and delivery.

Shared by the Celery digest tasks, the schedule runner, and the bot so the
"build a digest and send it" and "format an event list" logic lives in one
place instead of being copy-pasted across three modules.
"""
from app.constants import DEFAULT_DIGEST_HOURS
from app.services.digest_service import build_user_digest
from app.utils.text import truncate


async def send_digest_for_user(
    bot,
    user_id: int,
    db,
    hours: int = DEFAULT_DIGEST_HOURS,
    categories: list[str] | None = None,
    model: str | None = None,
) -> None:
    """Build the user's digest and DM it to them."""
    digest = await build_user_digest(db, user_id, hours=hours, categories=categories, model=model)
    text = truncate(digest.get("digest_markdown") or "Нет новых постов.")
    await bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")


def format_events_message(events: list[dict], *, limit: int = 10) -> str:
    """Render extracted events as a Markdown bullet list for Telegram."""
    if not events:
        return "📅 Нет предстоящих событий на ближайшие 7 дней."

    lines = ["📅 *Предстоящие события:*\n"]
    for ev in events[:limit]:
        name = ev.get("name") or "Событие"
        date = ev.get("date") or ""
        time_ = ev.get("time") or ""
        link = ev.get("link") or ""
        line = f"• *{name}* — {date} {time_}".strip()
        if link:
            line += f" [→]({link})"
        lines.append(line)
    return "\n".join(lines)
