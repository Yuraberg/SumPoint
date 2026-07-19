from fastapi import APIRouter

from app.api import (
    admin,
    auth,
    channels,
    chat,
    digest,
    favorites,
    health,
    posts,
    schedule,
    stats,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(channels.router)
api_router.include_router(posts.router)
api_router.include_router(favorites.router)
api_router.include_router(digest.router)
api_router.include_router(schedule.router)
api_router.include_router(stats.router)
api_router.include_router(chat.router)
api_router.include_router(admin.router)
api_router.include_router(health.router)
