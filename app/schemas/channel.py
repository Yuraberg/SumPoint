from datetime import datetime

from pydantic import BaseModel


class ChannelCreate(BaseModel):
    telegram_id: int = 0       # 0 means resolve by username
    username: str | None = None
    title: str = ""


class ChannelOut(BaseModel):
    id: int
    telegram_id: int
    username: str | None
    title: str
    category: str | None
    is_active: bool
    last_fetched_at: datetime | None
    last_error: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
