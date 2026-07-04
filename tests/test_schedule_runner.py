"""Unit tests for the cron schedule runner's due-row handling.

Covers the bug where an unparseable cron_expr disables the schedule
(status='disabled') instead of raising forever, and the happy path where a valid
expression advances next_run_at and executes.
"""
from types import SimpleNamespace

import pytest

from app.tasks import schedule_tasks


class _FakeSession:
    def __init__(self):
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def commit(self):
        self.commits += 1


def _sched(cron_expr, status="active"):
    return SimpleNamespace(
        id=1, name="s", cron_expr=cron_expr, status=status,
        schedule_type="topics", next_run_at=None, last_run_at=None,
        user_id=1, hours_back=24, categories=None, model="deepseek-v4-flash",
    )


def _wire(monkeypatch, due, executed):
    session = _FakeSession()
    monkeypatch.setattr(schedule_tasks, "AsyncSessionLocal", lambda: session)

    async def fake_claim(db, now):
        return due
    monkeypatch.setattr(schedule_tasks.schedule_repository, "claim_due", fake_claim)

    async def fake_exec(db, sched):
        executed.append(sched)
    monkeypatch.setattr(schedule_tasks, "_execute_schedule", fake_exec)
    return session


@pytest.mark.asyncio
async def test_bad_cron_disables_without_executing(monkeypatch):
    bad = _sched("this is not cron")
    executed = []
    _wire(monkeypatch, [bad], executed)

    await schedule_tasks._async_check_schedules()

    assert bad.status == "disabled"
    assert executed == []          # never executed
    assert bad.next_run_at is None


@pytest.mark.asyncio
async def test_valid_cron_advances_and_executes(monkeypatch):
    good = _sched("0 9 * * *")
    executed = []
    _wire(monkeypatch, [good], executed)

    await schedule_tasks._async_check_schedules()

    assert good.status == "active"
    assert good.next_run_at is not None   # advanced
    assert executed == [good]             # executed once
    assert good.last_run_at is not None


@pytest.mark.asyncio
async def test_execution_failure_does_not_crash_loop(monkeypatch):
    good = _sched("0 9 * * *")
    session = _wire(monkeypatch, [good], [])

    async def boom(db, sched):
        raise RuntimeError("delivery failed")
    monkeypatch.setattr(schedule_tasks, "_execute_schedule", boom)

    # Should swallow the execution error and still commit bookkeeping.
    await schedule_tasks._async_check_schedules()
    assert good.next_run_at is not None
