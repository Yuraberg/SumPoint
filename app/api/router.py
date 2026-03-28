from fastapi import APIRouter
from app.api import auth, channels, posts, digest

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(channels.router)
api_router.include_router(posts.router)
api_router.include_router(digest.router)
