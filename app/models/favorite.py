from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.utils.time import utcnow

# Posts have their own primary key; calendar events don't — they're a JSON
# list embedded in Post.events (see app/models/post.py). event_index lets one
# table cover both: -1 means "the post itself", 0+ indexes into that post's
# events array at the time it was favorited.
WHOLE_POST = -1


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (
        UniqueConstraint("user_id", "post_id", "event_index", name="uq_favorites_user_post_event"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    post_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False
    )
    event_index: Mapped[int] = mapped_column(Integer, nullable=False, default=WHOLE_POST)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
