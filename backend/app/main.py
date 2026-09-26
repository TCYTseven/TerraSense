"""TerraSense API. Run from backend/ with: uvicorn app.main:app --reload --port 8000"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from psycopg_pool import PoolTimeout

from app.config import cors_origins
from app.db import close_pool
from app.ml.readiness import setup_summary
from app.ml.tiles import TILES_DIR
from app.routes import forecast, mountains, runs

# The Next.js dev server, plus any deployed origins from CORS_ORIGINS.
# Browsers treat localhost and 127.0.0.1 as different origins.
FRONTEND_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000", *cors_origins()]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    import logging

    setup = setup_summary()
    if not setup["analyze_ready"]:
        logging.getLogger("app.main").warning(
            "Analyze is not ready (%s checks missing). Next: %s",
            setup["missing_count"],
            setup["next_step"],
        )
    yield
    close_pool()


app = FastAPI(title="TerraSense API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(mountains.router)
app.include_router(runs.router)
app.include_router(forecast.router)
# Map tiles rendered by ml/scripts/render_tiles.py. The folder may not exist until then.
app.mount("/tiles", StaticFiles(directory=TILES_DIR, check_dir=False), name="tiles")


@app.exception_handler(PoolTimeout)
@app.exception_handler(psycopg.OperationalError)
async def database_unavailable(_: Request, __: Exception) -> JSONResponse:
    """The database is down or unreachable. The frontend shows its error state."""
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


@app.get("/health")
def health(verbose: bool = False) -> dict:
    """Liveness check. ?verbose=1 adds local ML artifact status (no database)."""
    payload: dict = {"status": "ok"}
    if verbose:
        payload["setup"] = setup_summary()
    return payload
