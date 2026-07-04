"""Shared helpers for Celery tasks.

``run`` bridges the sync Celery task API to the async data/service layer, and
``get_bot`` re-exports the shared Bot factory so task modules don't reach into
each other. Keeping these here breaks the old "god module" import web.
"""
import asyncio

from app.database import _dispose_engine
from app.services.bot_service import get_bot  # noqa: F401  (re-exported)


def run(coro):
    """Run an async coroutine from a sync Celery task.

    asyncio.run() creates a fresh event loop, executes the coroutine, then runs
    all remaining callbacks (asyncpg connection-close finalizers) before tearing
    the loop down. This prevents the MissingGreenlet error that await_fallback()
    produced by leaving asyncpg cleanup callbacks scheduled after its greenlet
    context had already exited. The DB engine is disposed first so no connection
    from a previous task's (now-closed) loop is reused.
    """
    _dispose_engine()
    return asyncio.run(coro)
