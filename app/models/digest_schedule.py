from datetime import datetime
from sqlalchemy import BigInteger, Integer, String, Boolean, CheckConstraint, DateTime, JSON, UniqueConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

AVAILABLE_MODELS = ["deepseek-chat", "deepseek-reasoner"]
VALID_HOURS = [24, 72, 168]


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
    model: Mapped[str] = mapped_column(String(64), default="deepseek-chat")
    categories: Mapped[list | None] = mapped_column(JSON, nullable=True)  # None = all
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship("User", back_populates="schedules")
