"""DeepSeek peak / off-peak billing windows.

DeepSeek bills its V4 models at **double** the off-peak rate during two weekday
windows — 01:00-04:00 and 06:00-10:00 UTC, Monday to Friday, excluding Chinese
public holidays (https://api-docs.deepseek.com/quick_start/pricing). Every other
hour, all weekend, and every holiday are half price, so moving non-interactive
work into the off-peak window cuts its cost by 50%.

`app.tasks.enrich_tasks` uses this to drain posts whose DeepSeek enrichment was
deferred out of a peak window (``DEEPSEEK_OFFPEAK_ONLY`` in `app/config.py`).

Naive datetimes are treated as UTC — the DB stores naive UTC (`app.utils.time`).
"""

from datetime import datetime, timedelta, timezone

# (start_hour, end_hour) in UTC, half-open: peak while start <= hour < end.
# Values are straight from DeepSeek's pricing page — keep in sync with it.
PEAK_WINDOWS_UTC: tuple[tuple[int, int], ...] = ((1, 4), (6, 10))

# Hard stop for the "when does the cheap window open" scan below (5 days is
# more than enough to cross a weekend), so a bad clock can't spin forever.
_SCAN_HOURS = 24 * 5


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def is_peak(moment: datetime, holidays: frozenset[str] = frozenset()) -> bool:
    """Whether DeepSeek charges peak (2x) rates at ``moment``.

    ``holidays`` holds ISO dates (``YYYY-MM-DD``) of Chinese public holidays,
    which DeepSeek bills fully off-peak. A holiday we don't know about is
    treated as *peak*, which is the safe direction: the work is merely deferred
    into a window that was already cheap.
    """
    utc = _as_utc(moment)
    if utc.weekday() >= 5:  # Saturday/Sunday are off-peak all day
        return False
    if utc.date().isoformat() in holidays:
        return False
    return any(start <= utc.hour < end for start, end in PEAK_WINDOWS_UTC)


def is_offpeak(moment: datetime, holidays: frozenset[str] = frozenset()) -> bool:
    """Inverse of :func:`is_peak` — the half-price window."""
    return not is_peak(moment, holidays)


def next_offpeak_start(
    moment: datetime, holidays: frozenset[str] = frozenset()
) -> datetime:
    """UTC instant the current-or-next off-peak window opens.

    Returns ``moment`` itself when it is already off-peak. Used for log lines
    ("backlog drains at 10:00 UTC") so a skipped enrichment tick is not silent.
    """
    utc = _as_utc(moment)
    if is_offpeak(utc, holidays):
        return utc

    probe = utc.replace(minute=0, second=0, microsecond=0)
    for _ in range(_SCAN_HOURS):
        probe += timedelta(hours=1)
        if is_offpeak(probe, holidays):
            return probe
    return utc  # unreachable with sane windows; never return None
