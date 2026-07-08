from datetime import datetime
from typing import Any

from pydantic import BaseModel


class PostOut(BaseModel):
    id: int
    channel_id: int
    telegram_message_id: int
    text: str | None
    published_at: datetime
    summary: str | None
    category: str | None
    is_ad: bool
    events: Any | None
    channel_username: str | None = None
    channel_title: str | None = None
    similarity: float | None = None  # cosine distance for semantic search

    model_config = {"from_attributes": True}


class DigestOut(BaseModel):
    generated_at: datetime
    user_id: int
    posts: list[PostOut]
    events: list[dict]   # upcoming calendar events extracted from posts
