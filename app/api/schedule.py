"""Schedule management endpoints."""
from datetime import datetime
from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.constants import SCHEDULE_TYPES, AVAILABLE_MODELS
from app.models.schedule import Schedule
from app.schemas.schedule import ScheduleOut, ScheduleCreate, ScheduleUpdate
from app.repositories import schedule_repository
from app.api.deps import CurrentUser
from app.utils.time import utcnow

router = APIRouter(prefix="/schedule", tags=["schedule"])


def _next_run(cron_expr: str) -> datetime:
    return croniter(cron_expr, utcnow()).get_next(datetime)


def _validate(body: ScheduleCreate | ScheduleUpdate):
    schedule_type = getattr(body, "schedule_type", None)
    if schedule_type and schedule_type not in SCHEDULE_TYPES:
        raise HTTPException(400, f"schedule_type must be one of {SCHEDULE_TYPES}")
    if body.model and body.model not in AVAILABLE_MODELS:
        raise HTTPException(400, f"model must be one of {AVAILABLE_MODELS}")
    if body.cron_expr and not croniter.is_valid(body.cron_expr):
        raise HTTPException(400, "Invalid cron expression")


@router.get("/", response_model=list[ScheduleOut])
async def list_schedules(current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    return await schedule_repository.list_for_user(db, current_user.id)


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
    await db.flush()
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
    # updated_at is bumped automatically via the model's onupdate hook.
    await db.flush()
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
    await db.flush()
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


async def _get_own(db: AsyncSession, sched_id: int, user_id: int) -> Schedule:
    sched = await schedule_repository.get_owned(db, sched_id, user_id)
    if sched is None:
        raise HTTPException(404, "Schedule not found")
    return sched
