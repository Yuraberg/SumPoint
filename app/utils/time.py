"""Time helpers.

The database stores timestamps as ``TIMESTAMP WITHOUT TIME ZONE`` (see
CLAUDE.md), so every datetime written or compared must be *naive* UTC.
``datetime.utcnow()`` produced exactly that but is deprecated in Python 3.12+;
``utcnow()`` here is a drop-in replacement that stays naive without the warning.
"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return the current UTC time as a naive datetime (no tzinfo)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
