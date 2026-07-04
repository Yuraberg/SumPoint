"""Shared Telegram Bot factory for the worker.

PTB's ``Bot`` holds an HTTPX session that must be closed, so it is always used
as an async context manager (``async with get_bot() as bot:``). Centralising the
constructor keeps the token lookup and the context-manager contract in one place
instead of re-instantiating ``Bot`` ad hoc across task modules.
"""
from telegram import Bot

from app.config import get_settings


def get_bot() -> Bot:
    """Return a fresh ``Bot`` — use as ``async with get_bot() as bot: ...``."""
    return Bot(token=get_settings().telegram_bot_token)
