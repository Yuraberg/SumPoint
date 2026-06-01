"""FastAPI application entry point."""
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import os

from app.api.router import api_router
from app.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="SumPoint",
    description="Intelligent Telegram content processing — AI digest, classification & event extraction",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok"}


# Serve frontend SPA — catch-all must be LAST so API routes take priority
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(frontend_dir):
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve frontend files, falling back to index.html for SPA routing."""
        # Prevent directory traversal
        safe_path = os.path.normpath(full_path)
        if safe_path.startswith(".."):
            raise HTTPException(status_code=404, detail="Not Found")

        file_path = os.path.join(frontend_dir, safe_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)

        # SPA fallback — return index.html for any unknown path
        index_path = os.path.join(frontend_dir, "index.html")
        if os.path.isfile(index_path):
            return FileResponse(index_path)

        raise HTTPException(status_code=404, detail="Not Found")
