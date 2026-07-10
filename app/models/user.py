from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String
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

    # Access gate: a brand-new signup is approved instantly only if the owner
    # (Settings.owner_telegram_id_set) created them or they supplied a valid
    # invite code; otherwise they land here pending manual approval. Existing
    # users predating this feature were backfilled to True by the migration —
    # this never locks out someone already using the app.
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Bumped to invalidate every JWT already issued to this user (logout
    # everywhere / revoke on compromise). Each JWT carries the value it was
    # minted with as the "tv" claim; get_current_user rejects a mismatch.
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Digest preferences
    digest_morning: Mapped[bool] = mapped_column(Boolean, default=True)
    digest_evening: Mapped[bool] = mapped_column(Boolean, default=False)

    # Encrypted Telethon session file path
    session_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    channels: Mapped[list["Channel"]] = relationship("Channel", back_populates="user", cascade="all, delete-orphan")
    schedules: Mapped[list["DigestSchedule"]] = relationship("DigestSchedule", back_populates="user", cascade="all, delete-orphan")
    schedules_v2: Mapped[list["Schedule"]] = relationship("Schedule", back_populates="user", cascade="all, delete-orphan")
