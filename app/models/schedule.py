from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants import (  # noqa: F401  (re-exported for backward compatibility)
    AVAILABLE_MODELS,
    CRON_PRESETS,
    DEFAULT_MODEL,
    SCHEDULE_STATUSES,
    SCHEDULE_TYPES,
)
from app.database import Base
from app.utils.time import utcnow

if TYPE_CHECKING:
    from app.models.user import User


class Schedule(Base):
    __tablename__ = "schedules"
    __table_args__ = (
        CheckConstraint("schedule_type IN ('topics', 'events', 'collect')", name="ck_schedules_type"),
        CheckConstraint("status IN ('active', 'paused', 'disabled')", name="ck_schedules_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    schedule_type: Mapped[str] = mapped_column(String(32), default="topics")  # topics|events|collect
    cron_expr: Mapped[str] = mapped_column(String(64), default="0 9 * * *")
    hours_back: Mapped[int] = mapped_column(Integer, default=24)
    model: Mapped[str] = mapped_column(String(64), default=DEFAULT_MODEL)
    categories: Mapped[list | None] = mapped_column(JSON, nullable=True)   # None = all
    status: Mapped[str] = mapped_column(String(16), default="active")      # active|paused|disabled
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user: Mapped["User"] = relationship("User", back_populates="schedules_v2")
