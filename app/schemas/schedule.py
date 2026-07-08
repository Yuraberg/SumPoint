"""Pydantic schemas for the Schedule (v2 cron) API."""
from datetime import datetime

from pydantic import BaseModel

from app.constants import DEFAULT_MODEL


class ScheduleOut(BaseModel):
    id: int
    name: str
    schedule_type: str
    cron_expr: str
    hours_back: int
    model: str
    categories: list[str] | None
    status: str
    last_run_at: datetime | None
    next_run_at: datetime | None
    created_at: datetime
    model_config = {"from_attributes": True}


class ScheduleCreate(BaseModel):
    name: str
    schedule_type: str = "topics"
    cron_expr: str = "0 9 * * *"
    hours_back: int = 24
    model: str = DEFAULT_MODEL
    categories: list[str] | None = None


class ScheduleUpdate(BaseModel):
    name: str | None = None
    cron_expr: str | None = None
    hours_back: int | None = None
    model: str | None = None
    categories: list[str] | None = None
    status: str | None = None
