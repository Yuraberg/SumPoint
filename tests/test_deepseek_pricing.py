"""Unit tests for the DeepSeek peak / off-peak billing windows.

The two peak windows (01:00-04:00 and 06:00-10:00 UTC, weekdays only) decide when
SumPoint may spend money on DeepSeek, so the boundaries and the weekend/holiday
exemptions are pinned here: an off-by-one in either direction either wastes the
50% discount or pauses the pipeline on a day that was already cheap.

Reference dates: 2026-10-02 is a Friday, 03/04 Oct that weekend, 05 Oct Monday.
"""
from datetime import datetime, timedelta, timezone

from app.services.deepseek_pricing import (
    PEAK_WINDOWS_UTC,
    is_offpeak,
    is_peak,
    next_offpeak_start,
)

SAMARA = timezone(timedelta(hours=4))


def _utc(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


# ── Window boundaries (weekday) ───────────────────────────────────────────────

def test_hours_inside_first_window_are_peak():
    for hour in (1, 2, 3):
        assert is_peak(_utc(2026, 10, 5, hour)) is True


def test_first_window_ends_at_04_utc_exclusive():
    assert is_peak(_utc(2026, 10, 5, 3, 59)) is True
    assert is_peak(_utc(2026, 10, 5, 4, 0)) is False


def test_hours_inside_second_window_are_peak():
    for hour in (6, 7, 8, 9):
        assert is_peak(_utc(2026, 10, 5, hour)) is True


def test_second_window_ends_at_10_utc_exclusive():
    assert is_peak(_utc(2026, 10, 5, 9, 59)) is True
    assert is_peak(_utc(2026, 10, 5, 10, 0)) is False


def test_hours_between_the_windows_are_offpeak():
    # 04:00-06:00 UTC is the cheap gap in the middle of the night.
    assert is_peak(_utc(2026, 10, 5, 4, 30)) is False
    assert is_peak(_utc(2026, 10, 5, 5, 59)) is False


def test_evening_and_night_are_offpeak():
    for hour in (0, 11, 14, 23):
        assert is_peak(_utc(2026, 10, 5, hour)) is False


def test_whole_weekday_is_covered_by_the_two_windows():
    peak_hours = [h for h in range(24) if is_peak(_utc(2026, 10, 5, h))]
    assert peak_hours == [1, 2, 3, 6, 7, 8, 9]


# ── Weekends and holidays ─────────────────────────────────────────────────────

def test_weekend_is_offpeak_all_day():
    for day in (3, 4):  # Saturday, Sunday
        for hour in range(24):
            assert is_peak(_utc(2026, 10, day, hour)) is False


def test_friday_peak_still_applies():
    assert is_peak(_utc(2026, 10, 2, 8)) is True


def test_configured_holiday_is_offpeak_even_in_a_peak_window():
    assert is_peak(_utc(2026, 10, 5, 2), frozenset({"2026-10-05"})) is False
    assert is_peak(_utc(2026, 10, 5, 8), frozenset({"2026-10-05"})) is False


def test_unknown_holiday_defaults_to_safe_peak():
    """A holiday we don't know about must not cost us the pause — treating it as
    peak is the safe direction (work is only deferred into an already-cheap
    window)."""
    assert is_peak(_utc(2026, 10, 5, 8), frozenset({"2026-01-01"})) is True


# ── Time-zone handling ────────────────────────────────────────────────────────

def test_naive_datetime_is_treated_as_utc():
    # The DB stores naive UTC (app.utils.time.utcnow), so 02:00 naive == 02:00 UTC.
    assert is_peak(datetime(2026, 10, 5, 2, 0)) is True
    assert is_peak(datetime(2026, 10, 5, 12, 0)) is False


def test_aware_datetime_is_converted_to_utc():
    # 06:00 Samara (UTC+4) == 02:00 UTC — inside a peak window.
    assert is_peak(datetime(2026, 10, 5, 6, 0, tzinfo=SAMARA)) is True
    # 16:00 Samara == 12:00 UTC — off-peak.
    assert is_peak(datetime(2026, 10, 5, 16, 0, tzinfo=SAMARA)) is False


def test_is_offpeak_is_the_inverse_of_is_peak():
    for hour in range(24):
        moment = _utc(2026, 10, 5, hour)
        assert is_offpeak(moment) is not is_peak(moment)


# ── Next off-peak start ───────────────────────────────────────────────────────

def test_next_offpeak_start_returns_the_moment_itself_when_already_cheap():
    moment = _utc(2026, 10, 5, 12, 34)
    assert next_offpeak_start(moment) == moment


def test_next_offpeak_start_is_the_end_of_the_current_window():
    assert next_offpeak_start(_utc(2026, 10, 5, 1, 30)) == _utc(2026, 10, 5, 4, 0)
    assert next_offpeak_start(_utc(2026, 10, 5, 6, 0)) == _utc(2026, 10, 5, 10, 0)


def test_next_offpeak_start_from_fridays_last_window():
    # Friday 09:30 UTC is inside the second window; the cheap stretch starts at
    # 10:00 and runs through the whole weekend.
    assert next_offpeak_start(_utc(2026, 10, 9, 9, 30)) == _utc(2026, 10, 9, 10, 0)


def test_next_offpeak_start_honours_holidays():
    holidays = frozenset({"2026-10-05"})
    # Inside a window on a holiday: the answer is "right now", not 04:00.
    moment = _utc(2026, 10, 5, 2, 0)
    assert next_offpeak_start(moment, holidays) == moment


# ── Window table sanity ───────────────────────────────────────────────────────

def test_peak_windows_are_ordered_half_open_and_within_a_day():
    previous_end = 0
    for start, end in PEAK_WINDOWS_UTC:
        assert 0 <= start < end <= 24
        assert start >= previous_end          # no overlap, sorted
        previous_end = end
