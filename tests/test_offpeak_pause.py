"""Off-peak pause: automatic fetch ticks are skipped inside DeepSeek's peak
(half-price vs 2x) billing window when DEEPSEEK_OFFPEAK_ONLY is on.

Pinned behaviour:
  * the gate is opt-in — with the flag off nothing changes;
  * weekends/holidays are cheap, so they are never paused;
  * a paused tick touches neither Redis nor the DB (no lock, no Telethon);
  * the explicit "Sync" button (force=True) always runs;
  * /health/fetch reports an intentional pause as 200 "paused" instead of a
    false 503 "stale", so Uptime Kuma doesn't alarm for four hours a day.

Reference dates: 2026-10-02 Friday, 03/04 Oct weekend, 05 Oct Monday.
"""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import Response

from app.api import health
from app.tasks import fetch_tasks

PEAK = datetime(2026, 10, 5, 2, 0)          # Monday, inside 01:00-04:00 UTC
PEAK_LATE = datetime(2026, 10, 5, 8, 0)     # Monday, inside 06:00-10:00 UTC
OFFPEAK = datetime(2026, 10, 5, 12, 0)      # Monday, midday
WEEKEND = datetime(2026, 10, 3, 2, 0)       # Saturday, same hour as PEAK


def _settings(**overrides):
    """Stand-in for Settings with only the fields these code paths read."""
    base = {
        "deepseek_offpeak_only": True,
        "deepseek_holiday_set": frozenset(),
        "posts_fetch_interval_minutes": 20,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def peak_clock(monkeypatch):
    """Pin the fetch task's clock to a weekday peak instant."""
    monkeypatch.setattr(fetch_tasks, "utcnow", lambda: PEAK)


# ── The gate itself ───────────────────────────────────────────────────────────

def test_paused_during_a_peak_window(monkeypatch):
    monkeypatch.setattr(fetch_tasks, "get_settings", lambda: _settings())
    assert fetch_tasks._paused_for_peak(PEAK) is True
    assert fetch_tasks._paused_for_peak(PEAK_LATE) is True


def test_disabled_flag_never_pauses(monkeypatch):
    monkeypatch.setattr(
        fetch_tasks, "get_settings", lambda: _settings(deepseek_offpeak_only=False)
    )
    assert fetch_tasks._paused_for_peak(PEAK) is False


def test_offpeak_hours_are_not_paused(monkeypatch):
    monkeypatch.setattr(fetch_tasks, "get_settings", lambda: _settings())
    assert fetch_tasks._paused_for_peak(OFFPEAK) is False


def test_weekend_is_never_paused(monkeypatch):
    monkeypatch.setattr(fetch_tasks, "get_settings", lambda: _settings())
    assert fetch_tasks._paused_for_peak(WEEKEND) is False


def test_holiday_is_never_paused(monkeypatch):
    monkeypatch.setattr(
        fetch_tasks,
        "get_settings",
        lambda: _settings(deepseek_holiday_set=frozenset({"2026-10-05"})),
    )
    assert fetch_tasks._paused_for_peak(PEAK) is False


# ── The tick ──────────────────────────────────────────────────────────────────

class _LockSpy:
    def __init__(self, result=None):
        self.calls = 0
        self._result = result

    async def __call__(self):
        self.calls += 1
        return self._result


@pytest.mark.asyncio
async def test_peak_tick_is_skipped_without_touching_the_lock(monkeypatch, peak_clock):
    monkeypatch.setattr(fetch_tasks, "get_settings", lambda: _settings())
    spy = _LockSpy()
    monkeypatch.setattr(fetch_tasks, "_try_acquire_fetch_lock", spy)

    await fetch_tasks._async_fetch_all()

    assert spy.calls == 0  # no Redis, no Telethon, no DeepSeek spend


@pytest.mark.asyncio
async def test_offpeak_tick_runs_normally(monkeypatch):
    monkeypatch.setattr(fetch_tasks, "get_settings", lambda: _settings())
    monkeypatch.setattr(fetch_tasks, "utcnow", lambda: OFFPEAK)
    spy = _LockSpy(result=None)  # None = "another run holds the lock"
    monkeypatch.setattr(fetch_tasks, "_try_acquire_fetch_lock", spy)

    await fetch_tasks._async_fetch_all()

    assert spy.calls == 1


@pytest.mark.asyncio
async def test_force_bypasses_the_peak_pause(monkeypatch, peak_clock):
    """The user's explicit Sync click must work inside a peak window."""
    monkeypatch.setattr(fetch_tasks, "get_settings", lambda: _settings())
    spy = _LockSpy(result=None)
    monkeypatch.setattr(fetch_tasks, "_try_acquire_fetch_lock", spy)

    await fetch_tasks._async_fetch_all(force=True)

    assert spy.calls == 1


def test_manual_sync_endpoint_forces_the_fetch(monkeypatch):
    """Guard the API wiring: /channels/sync must dispatch force=True, otherwise
    the button silently does nothing for hours inside a peak window."""
    from app.api import channels
    from app.tasks import fetch_tasks as fetch_module

    dispatched = []
    fake_task = SimpleNamespace(delay=lambda **kwargs: dispatched.append(kwargs))
    monkeypatch.setattr(fetch_module, "fetch_all_channels", fake_task)

    asyncio.run(channels.sync_subscriptions(current_user=SimpleNamespace(id=1)))

    assert dispatched == [{"force": True}]


# ── /health/fetch ─────────────────────────────────────────────────────────────

class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeSession:
    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, *_args, **_kwargs):
        return _FakeResult(self._value)


def _session_factory(value):
    return lambda: _FakeSession(value)


@pytest.mark.asyncio
async def test_fetch_health_reports_paused_instead_of_stale(monkeypatch):
    monkeypatch.setattr(health, "get_settings", lambda: _settings())
    monkeypatch.setattr(health, "utcnow", lambda: PEAK)
    # An hour old = way past 2x the 20-minute interval.
    monkeypatch.setattr(health, "AsyncSessionLocal", _session_factory(PEAK - timedelta(hours=1)))

    response = Response()
    payload = await health.fetch_health_check(response)

    assert payload["status"] == "paused"
    assert response.status_code == 200  # monitor stays green
    assert payload["resumes_at"] == "2026-10-05T04:00:00+00:00"


@pytest.mark.asyncio
async def test_fetch_health_is_stale_when_not_in_a_peak_window(monkeypatch):
    """The 2026-07-04 wedged-worker signal must survive this change."""
    monkeypatch.setattr(health, "get_settings", lambda: _settings())
    monkeypatch.setattr(health, "utcnow", lambda: OFFPEAK)
    monkeypatch.setattr(health, "AsyncSessionLocal", _session_factory(OFFPEAK - timedelta(hours=1)))

    response = Response()
    payload = await health.fetch_health_check(response)

    assert payload["status"] == "stale"
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_fetch_health_is_stale_in_peak_with_the_flag_off(monkeypatch):
    monkeypatch.setattr(
        health, "get_settings", lambda: _settings(deepseek_offpeak_only=False)
    )
    monkeypatch.setattr(health, "utcnow", lambda: PEAK)
    monkeypatch.setattr(health, "AsyncSessionLocal", _session_factory(PEAK - timedelta(hours=1)))

    response = Response()
    payload = await health.fetch_health_check(response)

    assert payload["status"] == "stale"
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_fetch_health_is_healthy_when_fresh(monkeypatch):
    monkeypatch.setattr(health, "get_settings", lambda: _settings())
    monkeypatch.setattr(health, "utcnow", lambda: OFFPEAK)
    monkeypatch.setattr(health, "AsyncSessionLocal", _session_factory(OFFPEAK - timedelta(minutes=5)))

    response = Response()
    payload = await health.fetch_health_check(response)

    assert payload["status"] == "healthy"
    assert response.status_code == 200
