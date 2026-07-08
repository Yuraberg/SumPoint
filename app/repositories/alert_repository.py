"""Keyword-alert queries."""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.keyword_alert import KeywordAlert


async def list_for_user(db: AsyncSession, user_id: int) -> list[KeywordAlert]:
    return (
        await db.execute(
            select(KeywordAlert)
            .where(KeywordAlert.user_id == user_id)
            .order_by(KeywordAlert.keyword)
        )
    ).scalars().all()


async def count_for_user(db: AsyncSession, user_id: int) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(KeywordAlert).where(
                KeywordAlert.user_id == user_id
            )
        )
    ).scalar_one()


async def get(db: AsyncSession, user_id: int, keyword: str) -> KeywordAlert | None:
    return (
        await db.execute(
            select(KeywordAlert).where(
                KeywordAlert.user_id == user_id, KeywordAlert.keyword == keyword
            )
        )
    ).scalar_one_or_none()
