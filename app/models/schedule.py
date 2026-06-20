from datetime import datetime
from sqlalchemy import BigInteger, CheckConstraint, Integer, String, DateTime, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

SCHEDULE_TYPES = ["topics", "events", "collect"]
AVAILABLE_MODELS = ["deepseek-chat", "deepseek-reasoner"]

_TYPE_LABELS = {"topics": "Темы", "events": "События", "collect": "Сбор"}

CRON_PRESETS = {
    "0 9 * * *":   "Каждый день в 09:00",
    "0 12 * * *":  "Каждый день в 12:00",
    "0 21 * * *":  "Каждый день в 21:00",
    "0 */6 * * *": "Каждые 6 часов",
    "0 * * * *":   "Каждый час",
    "*/30 * * * *":"Каждые 30 минут",
}


class Schedule(Base):
    __tablename__ = "schedules"
    __table_args__ = (
        CheckConstraint("schedule_type IN ('topics', 'events', 'collect')", name="ck_schedules_type"),
        CheckConstraint("status IN ('active', 'paused')", name="ck_schedules_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    schedule_type: Mapped[str] = mapped_column(String(32), default="topics")  # topics|events|collect
    cron_expr: Mapped[str] = mapped_column(String(64), default="0 9 * * *")
    hours_back: Mapped[int] = mapped_column(Integer, default=24)
    model: Mapped[str] = mapped_column(String(64), default="deepseek-chat")
    categories: Mapped[list | None] = mapped_column(JSON, nullable=True)   # None = all
    status: Mapped[str] = mapped_column(String(16), default="active")      # active|paused
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship("User", back_populates="schedules_v2")
