"""Settings from the repo root .env. Variables already set in the environment win."""

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(REPO_ROOT / ".env")


def database_url() -> str:
    """Return DATABASE_URL, or raise with the fix if it is missing."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env at the repo root and fill it in."
        )
    return url
