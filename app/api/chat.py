"""RAG assistant — answer questions grounded in the user's own posts."""
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.database import get_db
from app.rate_limit import limiter
from app.services import rag_service

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatIn(BaseModel):
    question: str = Field(..., min_length=2, max_length=1000)


class ChatSource(BaseModel):
    id: int
    channel_id: int
    telegram_message_id: int
    channel_username: str | None = None
    channel_title: str | None = None
    published_at: datetime | None = None
    snippet: str | None = None


class ChatOut(BaseModel):
    answer: str
    sources: list[ChatSource]


@router.post("/ask", response_model=ChatOut)
@limiter.limit("15/minute")
async def ask(
    request: Request,
    data: ChatIn,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Answer a question using semantic retrieval over the user's posts + LLM.
    Rate-limited because each call hits both the embedding model and DeepSeek."""
    result = await rag_service.answer_question(db, current_user.id, data.question)
    return result
