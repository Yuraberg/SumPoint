"""Schedule management endpoints."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.schedule import Schedule, SCHEDULE_TYPES, AVAILABLE_MODELS
from app.api.deps import CurrentUser

router = APIRouter(prefix="/schedule", tags=["schedule"])


def _next_run(cron_expr: str) -> datetime:
    from croniter import croniter
    return croniter(cron_expr, datetime.utcnow()).get_next(datetime)


class ScheduleOut(BaseModel):
    id: int
    name: str
    schedule_type: str
    cron_expr: str
    hours_back: int
    model: str
    categories: list[str] | None
    status: str
    last_run_at: datetime | None
    next_run_at: datetime | None
    created_at: datetime
    model_config = {"from_attributes": True}


class ScheduleCreate(BaseModel):
    name: str
    schedule_type: str = "topics"
    cron_expr: str = "0 9 * * *"
    hours_back: int = 24
    model: str = "deepseek-v4-flash"
    categories: list[str] | None = None


class ScheduleUpdate(BaseModel):
    name: str | None = None
    cron_expr: str | None = None
    hours_back: int | None = None
    model: str | None = None
    categories: list[str] | None = None
    status: str | None = None


def _validate(body: ScheduleCreate | ScheduleUpdate):
    if hasattr(body, "schedule_type") and body.schedule_type and body.schedule_type not in SCHEDULE_TYPES:
        raise HTTPException(400, f"schedule_type must be one of {SCHEDULE_TYPES}")
    if hasattr(body, "model") and body.model and body.model not in AVAILABLE_MODELS:
        raise HTTPException(400, f"model must be one of {AVAILABLE_MODELS}")
    if hasattr(body, "cron_expr") and body.cron_expr:
        try:
            from croniter import croniter
            if not croniter.is_valid(body.cron_expr):
                raise HTTPException(400, "Invalid cron expression")
        except ImportError:
            pass


@router.get("/", response_model=list[ScheduleOut])
async def list_schedules(current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(Schedule)
            .where(Schedule.user_id == current_user.id)
            .order_by(Schedule.created_at.desc())
        )
    ).scalars().all()
    return rows


@router.post("/", response_model=ScheduleOut, status_code=201)
async def create_schedule(
    body: ScheduleCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    _validate(body)
    sched = Schedule(
        user_id=current_user.id,
        name=body.name,
        schedule_type=body.schedule_type,
        cron_expr=body.cron_expr,
        hours_back=body.hours_back,
        model=body.model,
        categories=body.categories or None,
        status="active",
        next_run_at=_next_run(body.cron_expr),
    )
    db.add(sched)
    await db.commit()
    await db.refresh(sched)
    return sched


@router.put("/{sched_id}", response_model=ScheduleOut)
async def update_schedule(
    sched_id: int,
    body: ScheduleUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    sched = await _get_own(db, sched_id, current_user.id)
    _validate(body)
    if body.name is not None:
        sched.name = body.name
    if body.cron_expr is not None:
        sched.cron_expr = body.cron_expr
        sched.next_run_at = _next_run(body.cron_expr)
    if body.hours_back is not None:
        sched.hours_back = body.hours_back
    if body.model is not None:
        sched.model = body.model
    if body.categories is not None:
        sched.categories = body.categories or None
    if body.status is not None:
        sched.status = body.status
    sched.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(sched)
    return sched


@router.post("/{sched_id}/toggle", response_model=ScheduleOut)
async def toggle_schedule(
    sched_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    sched = await _get_own(db, sched_id, current_user.id)
    sched.status = "paused" if sched.status == "active" else "active"
    if sched.status == "active":
        sched.next_run_at = _next_run(sched.cron_expr)
    sched.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(sched)
    return sched


@router.delete("/{sched_id}", status_code=204)
async def delete_schedule(
    sched_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    sched = await _get_own(db, sched_id, current_user.id)
    await db.delete(sched)
    await db.commit()


async def _get_own(db: AsyncSession, sched_id: int, user_id: int) -> Schedule:
    sched = (
        await db.execute(
            select(Schedule).where(Schedule.id == sched_id, Schedule.user_id == user_id)
        )
    ).scalar_one_or_none()
    if sched is None:
        raise HTTPException(404, "Schedule not found")
    return sched
