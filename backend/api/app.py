"""FastAPI application factory."""
from __future__ import annotations
import logging
import os
from pathlib import Path

import colorlog
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

load_dotenv()

handler = colorlog.StreamHandler()
handler.setFormatter(colorlog.ColoredFormatter(
    "%(log_color)s%(levelname)-8s%(reset)s %(blue)s%(name)s%(reset)s  %(message)s"
))
logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO"), handlers=[handler])

FRONTEND = Path(__file__).parents[2] / "frontend"


def create_app() -> FastAPI:
    from .routes import router

    app = FastAPI(title="AstroAgent v2", version="2.0.0", docs_url="/api/docs")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"],
        allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
    )
    app.include_router(router, prefix="/api")

    static = FRONTEND / "static"
    if static.exists():
        app.mount("/static", StaticFiles(directory=str(static)), name="static")

    index = FRONTEND / "templates" / "index.html"

    @app.get("/{full_path:path}")
    async def spa(full_path: str = ""):
        if full_path.startswith("api"):
            from fastapi import HTTPException
            raise HTTPException(404)
        if index.exists():
            return FileResponse(str(index))
        return {"status": "AstroAgent v2 API — frontend not found"}

    @app.on_event("startup")
    async def _up():
        logging.getLogger("astroagent").info("AstroAgent v2 ready — http://localhost:%s", os.getenv("APP_PORT","8000"))

    return app


app = create_app()
