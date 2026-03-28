from pydantic import BaseModel
from datetime import datetime


class UserOut(BaseModel):
    id: int
    username: str | None
    first_name: str
    digest_morning: bool
    digest_evening: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    digest_morning: bool | None = None
    digest_evening: bool | None = None
