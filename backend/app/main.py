"""TerraSense API. Run from backend/ with: uvicorn app.main:app --reload --port 8000"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# The Next.js dev server. Browsers treat localhost and 127.0.0.1 as different origins.
FRONTEND_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]

app = FastAPI(title="TerraSense API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check for the frontend and for curl."""
    return {"status": "ok"}
