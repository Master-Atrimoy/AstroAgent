"""FastAPI application factory."""
from __future__ import annotations
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from backend.api.routes import router

STATIC_DIR = Path(__file__).parents[2] / "static"

app = FastAPI(
    title="DeepSkyAgent",
    description="AI-powered telescope observation planner — AstroAgent v2",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/", include_in_schema=False)
def root():
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/{path:path}", include_in_schema=False)
def catch_all(path: str):
    # Serve index.html for any unknown path (SPA-style)
    target = STATIC_DIR / path
    if target.exists() and target.is_file():
        return FileResponse(target)
    return FileResponse(STATIC_DIR / "index.html")
