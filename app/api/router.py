from fastapi import APIRouter

from app.api import auth, channels, digest, health, posts, schedule, stats

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(channels.router)
api_router.include_router(posts.router)
api_router.include_router(digest.router)
api_router.include_router(schedule.router)
api_router.include_router(stats.router)
api_router.include_router(health.router)
