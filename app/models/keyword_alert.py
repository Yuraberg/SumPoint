from datetime import datetime
from sqlalchemy import BigInteger, Integer, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
from app.utils.time import utcnow


class KeywordAlert(Base):
    __tablename__ = "keyword_alerts"
    __table_args__ = (
        UniqueConstraint("user_id", "keyword", name="uq_keyword_alerts_user_keyword"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    keyword: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
