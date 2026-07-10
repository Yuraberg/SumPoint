import secrets
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.utils.time import utcnow


def _gen_code() -> str:
    """8 uppercase hex chars — short enough to type/read aloud, long enough
    (32 bits) that guessing isn't practical within the invite's lifetime."""
    return secrets.token_hex(4).upper()


class InviteCode(Base):
    __tablename__ = "invite_codes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, default=_gen_code)
    # Telegram id of the owner who generated it (for audit; not a FK since the
    # creator doesn't have to be a `users` row, e.g. bootstrap before first login).
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    max_uses: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    uses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    note: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
