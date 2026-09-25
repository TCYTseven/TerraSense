"""TerraSense API. Run from backend/ with: uvicorn app.main:app --reload --port 8000"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout

from app.config import cors_origins
from app.db import close_pool
from app.routes import mountains

# The Next.js dev server, plus any deployed origins from CORS_ORIGINS.
# Browsers treat localhost and 127.0.0.1 as different origins.
FRONTEND_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000", *cors_origins()]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
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


@app.exception_handler(PoolTimeout)
@app.exception_handler(psycopg.OperationalError)
async def database_unavailable(_: Request, __: Exception) -> JSONResponse:
    """The database is down or unreachable. The frontend shows its error state."""
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check for the frontend and for curl. Does not touch the database."""
    return {"status": "ok"}
