from datetime import datetime
from sqlalchemy import BigInteger, Integer, String, Boolean, CheckConstraint, DateTime, JSON, UniqueConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.constants import (  # noqa: F401  (re-exported for backward compatibility)
    AVAILABLE_MODELS,
    DEFAULT_MODEL,
    VALID_DIGEST_HOURS as VALID_HOURS,
)
from app.utils.time import utcnow


class DigestSchedule(Base):
    __tablename__ = "digest_schedules"
    __table_args__ = (
        UniqueConstraint("user_id", "slot", name="uq_user_slot"),
        CheckConstraint("slot IN ('morning', 'evening')", name="ck_digest_schedules_slot"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    slot: Mapped[str] = mapped_column(String(16), nullable=False)   # "morning" | "evening"
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    hours_back: Mapped[int] = mapped_column(Integer, default=24)    # 24 | 72 | 168
    model: Mapped[str] = mapped_column(String(64), default=DEFAULT_MODEL)
    categories: Mapped[list | None] = mapped_column(JSON, nullable=True)  # None = all
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user: Mapped["User"] = relationship("User", back_populates="schedules")
