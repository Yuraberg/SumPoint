"""Data-access layer.

Repositories centralise the SQLAlchemy queries that were previously duplicated
across API routers, Celery tasks, and bot handlers. Each function takes an
``AsyncSession`` and returns ORM objects / rows — transaction management
(commit/rollback) stays with the caller.
"""
