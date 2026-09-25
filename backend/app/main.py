"""TerraSense API. Run from backend/ with: uvicorn app.main:app --reload --port 8000"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import close_pool
from app.routes import mountains

# The Next.js dev server. Browsers treat localhost and 127.0.0.1 as different origins.
FRONTEND_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]


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


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check for the frontend and for curl. Does not touch the database."""
    return {"status": "ok"}
