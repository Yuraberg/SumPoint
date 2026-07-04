"""Collect and sort upcoming events from post.events JSON fields."""
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import DEFAULT_DIGEST_HOURS  # noqa: F401  (kept for parity)
from app.repositories import post_repository

_DEFAULT_DAYS_AHEAD = 7


@dataclass
class _EventContext:
    """One extracted event plus the channel/post metadata it came from."""
    event: dict
    ev_date: date | None
    channel_title: str | None
    channel_username: str | None
    post_category: str | None


async def get_upcoming_events(
    db: AsyncSession,
    user_id: int,
    days_ahead: int = _DEFAULT_DAYS_AHEAD,
    date_from: date | None = None,
    date_to: date | None = None,
    event_type: str | None = None,
) -> list[dict]:
    """Return events extracted from posts, enriched with channel info and mention counts."""
    rows = await post_repository.get_events_feed(db, user_id)

    today = date.today()
    cutoff_from = date_from or today
    cutoff_to = date_to or (today + timedelta(days=days_ahead))

    # Collect all matching events with their source context.
    collected: list[_EventContext] = []
    for row in rows:
        post_events = row.events if isinstance(row.events, list) else []
        for ev in post_events:
            if not isinstance(ev, dict):
                continue

            ev_date = _parse_date(ev.get("date"))
            if ev_date and (ev_date < cutoff_from or ev_date > cutoff_to):
                continue
            if event_type and ev.get("type", "").lower() != event_type.lower():
                continue

            collected.append(
                _EventContext(
                    event=ev,
                    ev_date=ev_date,
                    channel_title=row.channel_title,
                    channel_username=row.channel_username,
                    post_category=row.category,
                )
            )

    # Count mentions per (name, date) so the same event on different days stays
    # distinct while genuine cross-channel duplicates are merged.
    def _key(ctx: _EventContext) -> tuple[str, str]:
        name = (ctx.event.get("name") or "").strip().lower()
        return name, (ctx.event.get("date") or "")

    mention_counts: Counter = Counter(_key(c) for c in collected if c.event.get("name"))

    seen: set[tuple[str, str]] = set()
    result: list[dict] = []
    for ctx in collected:
        key = _key(ctx)
        name = key[0]
        if name and key in seen:
            continue
        if name:
            seen.add(key)

        clean = {k: v for k, v in ctx.event.items() if not k.startswith("_")}
        clean["channel_title"] = ctx.channel_title
        clean["channel_username"] = ctx.channel_username
        clean["post_category"] = ctx.post_category
        clean["mentions"] = mention_counts.get(key, 1) if name else 1
        result.append(clean)

    result.sort(key=lambda e: e.get("date") or "9999-12-31")
    return result


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None
