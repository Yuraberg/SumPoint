from datetime import datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants import EMBEDDING_DIM  # noqa: F401  (re-exported)
from app.database import Base
from app.utils.time import utcnow

if TYPE_CHECKING:
    from app.models.channel import Channel


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        UniqueConstraint("channel_id", "telegram_message_id", name="uq_posts_channel_message"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("channels.id", ondelete="CASCADE"))
    telegram_message_id: Mapped[int] = mapped_column(Integer)

    # SHA-256 of the post text — used to dedup reposted/identical content
    # across runs (the message-id constraint above only catches re-fetches
    # of the *same* Telegram message).
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # Raw content
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime)

    # AI-generated fields
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_ad: Mapped[bool] = mapped_column(Boolean, default=False)
    events: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)  # list of {date, time, name, link}

    # pgvector embedding for semantic search
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)

    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    channel: Mapped["Channel"] = relationship("Channel", back_populates="posts")
