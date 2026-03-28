from pydantic import BaseModel
from datetime import datetime


class ChannelCreate(BaseModel):
    telegram_id: int
    username: str | None = None
    title: str


class ChannelOut(BaseModel):
    id: int
    telegram_id: int
    username: str | None
    title: str
    category: str | None
    is_active: bool
    last_fetched_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}
