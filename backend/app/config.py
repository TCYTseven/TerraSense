"""Settings from the repo root .env. Variables already set in the environment win."""

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(REPO_ROOT / ".env")

DbTarget = Literal["LOCAL", "PROD"]


def db_target() -> DbTarget:
    """Which Postgres instance to use: local dev or Tiger Cloud (TimescaleDB)."""
    raw = os.environ.get("DB", "LOCAL").strip().upper()
    if raw not in ("LOCAL", "PROD"):
        raise RuntimeError("DB must be LOCAL or PROD.")
    return raw  # type: ignore[return-value]


def cors_origins() -> list[str]:
    """Extra browser origins from CORS_ORIGINS, comma-separated, such as a deployed frontend."""
    raw = os.environ.get("CORS_ORIGINS", "")
    return [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]


def database_url() -> str:
    """Postgres URL for the active DB target (LOCAL or PROD).

    Prefer DATABASE_URL_LOCAL / DATABASE_URL_PROD when DB is set. DATABASE_URL alone still
    works for older setups and tests that set it directly.
    """
    target = db_target()
    keyed = (
        os.environ.get("DATABASE_URL_PROD" if target == "PROD" else "DATABASE_URL_LOCAL", "").strip()
    )
    if keyed:
        return keyed
    legacy = os.environ.get("DATABASE_URL", "").strip()
    if legacy:
        return legacy
    var = "DATABASE_URL_PROD" if target == "PROD" else "DATABASE_URL_LOCAL"
    raise RuntimeError(
        f"{var} is not set (DB={target}). Copy .env.example to .env at the repo root and fill it in."
    )
