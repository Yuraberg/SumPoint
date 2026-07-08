from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.utils.time import utcnow

if TYPE_CHECKING:
    from app.models.channel import Channel
    from app.models.digest_schedule import DigestSchedule
    from app.models.schedule import Schedule


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)           # Telegram user ID
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # Telegram chat ID for bot DM

    # Digest preferences
    digest_morning: Mapped[bool] = mapped_column(Boolean, default=True)
    digest_evening: Mapped[bool] = mapped_column(Boolean, default=False)

    # Encrypted Telethon session file path
    session_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    channels: Mapped[list["Channel"]] = relationship("Channel", back_populates="user", cascade="all, delete-orphan")
    schedules: Mapped[list["DigestSchedule"]] = relationship("DigestSchedule", back_populates="user", cascade="all, delete-orphan")
    schedules_v2: Mapped[list["Schedule"]] = relationship("Schedule", back_populates="user", cascade="all, delete-orphan")
