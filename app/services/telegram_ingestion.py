"""
Telegram User API data ingestion via Telethon.

Responsibilities:
  - Connect to Telegram on behalf of the user (using encrypted session)
  - Stream new messages in real-time
  - Fetch historical messages (last N hours)
  - Pre-filter: strip ads, duplicates, service notifications
"""
import asyncio
import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import Message, Channel as TLChannel

from app.config import get_settings
from app.services.encryption import load_decrypted, save_encrypted

logger = logging.getLogger(__name__)
settings = get_settings()

# Heuristics for ad detection
_AD_KEYWORDS = {"реклама", "спонсор", "промокод", "скидка", "#реклама", "#ad", "#sponsor", "партнёрский"}


def _is_ad(text: str) -> bool:
    if not text:
        return False
    lower = text.lower()
    return any(kw in lower for kw in _AD_KEYWORDS)


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class TelegramIngestion:
    def __init__(self, user_id: int, session_path: str):
        self._user_id = user_id
        self._session_path = session_path
        self._client: TelegramClient | None = None
        self._seen_hashes: set[str] = set()

    # ── Session management ─────────────────────────────────────────────────────

    def _load_session_string(self) -> str | None:
        if not os.path.exists(self._session_path):
            return None
        try:
            raw = load_decrypted(self._session_path)
            return raw.decode()
        except Exception as e:
            logger.warning("Failed to load session for user %s: %s", self._user_id, e)
            return None

    def _save_session_string(self, session_str: str) -> None:
        save_encrypted(self._session_path, session_str.encode())

    async def _get_client(self) -> TelegramClient:
        if self._client and self._client.is_connected():
            return self._client
        session_str = self._load_session_string()
        session = StringSession(session_str) if session_str else StringSession()
        client = TelegramClient(session, settings.telegram_api_id, settings.telegram_api_hash)
        await client.start()
        # Persist updated session
        self._save_session_string(client.session.save())
        self._client = client
        return client

    async def disconnect(self) -> None:
        if self._client:
            await self._client.disconnect()
            self._client = None

    # ── Channel discovery ──────────────────────────────────────────────────────

    async def get_subscribed_channels(self) -> list[dict]:
        """Return all channels the user is subscribed to."""
        client = await self._get_client()
        channels = []
        async for dialog in client.iter_dialogs():
            entity = dialog.entity
            if isinstance(entity, TLChannel) and entity.broadcast:
                channels.append({
                    "telegram_id": entity.id,
                    "username": getattr(entity, "username", None),
                    "title": entity.title,
                })
        return channels

    # ── Historical fetch ───────────────────────────────────────────────────────

    async def fetch_recent_posts(self, channel_id: int, hours: int = 24) -> AsyncIterator[dict]:
        """Yield posts from the last `hours` hours, pre-filtered."""
        client = await self._get_client()
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
        async for msg in client.iter_messages(channel_id, limit=500):
            if not isinstance(msg, Message):
                continue
            if msg.date < cutoff:
                break
            post = self._process_message(msg)
            if post:
                yield post

    # ── Real-time monitoring ───────────────────────────────────────────────────

    async def start_realtime_monitoring(self, channel_ids: list[int], callback) -> None:
        """Register a new-message handler for the given channels."""
        client = await self._get_client()

        @client.on(events.NewMessage(chats=channel_ids))
        async def handler(event):
            msg: Message = event.message
            post = self._process_message(msg)
            if post:
                await callback(post)

        await client.run_until_disconnected()

    # ── Pre-processing ─────────────────────────────────────────────────────────

    def _process_message(self, msg: Message) -> dict | None:
        text = (msg.text or "").strip()
        if not text or len(text) < 20:
            return None

        # Dedup
        h = _content_hash(text)
        if h in self._seen_hashes:
            return None
        self._seen_hashes.add(h)

        return {
            "telegram_message_id": msg.id,
            "channel_telegram_id": msg.peer_id.channel_id if hasattr(msg.peer_id, "channel_id") else 0,
            "text": text,
            "published_at": msg.date,
            "is_ad": _is_ad(text),
        }
