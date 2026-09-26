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
from app.ml.geo_susceptibility import predict_summit
from app.ml.readiness import setup_summary
from app.ml.tiles import TILES_DIR
from app.routes import forecast, mountains, risk, runs, simulations, synthetic_tiles

# The Next.js dev server, plus any deployed origins from CORS_ORIGINS.
# Browsers treat localhost and 127.0.0.1 as different origins.
FRONTEND_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000", *cors_origins()]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    import asyncio
    import logging

    setup = setup_summary()
    if not setup["analyze_ready"]:
        logging.getLogger("app.main").warning(
            "Analyze is not ready (%s checks missing). Next: %s",
            setup["missing_count"],
            setup["next_step"],
        )
    # Warm the regional model seam (booster + feature stack) once at boot, so the first
    # GET /mountains and the first location run do not pay the raster read. Fail-soft: with
    # the artifacts unbuilt this returns available: false and costs nothing.
    await asyncio.to_thread(predict_summit, "startup-warmup", 0.0, 0.0)
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
app.include_router(simulations.router)
app.include_router(runs.router)
app.include_router(forecast.router)
app.include_router(risk.router)
app.include_router(synthetic_tiles.router)
# Map tiles rendered by ml/scripts/render_tiles.py. The folder may not exist until then.
app.mount("/tiles", StaticFiles(directory=TILES_DIR, check_dir=False), name="tiles")


@app.exception_handler(PoolTimeout)
@app.exception_handler(psycopg.OperationalError)
async def database_unavailable(_: Request, __: Exception) -> JSONResponse:
    """The database is down or unreachable. The frontend shows its error state."""
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


@app.get("/")
def root() -> dict[str, str]:
    """Browser-friendly entry point; the UI runs on http://localhost:3000."""
    return {
        "service": "TerraSense API",
        "health": "/health",
        "docs": "/docs",
        "mountains": "/mountains",
    }


@app.get("/json/version")
def chrome_devtools_probe() -> dict[str, str]:
    """Chrome DevTools probes localhost ports; not a CDP target."""
    return {"Browser": "TerraSense API", "Protocol-Version": "1.0"}


@app.get("/health")
def health(verbose: bool = False) -> dict:
    """Liveness check. ?verbose=1 adds local ML artifact status (no database)."""
    payload: dict = {"status": "ok"}
    if verbose:
        payload["setup"] = setup_summary()
    return payload
