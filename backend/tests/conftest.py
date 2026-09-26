"""Shared test setup. Run from backend/: python -m pytest"""

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


@pytest.fixture(scope="session")
def db_conn():
    """A connection to DATABASE_URL, or a skip when no database answers."""
    import psycopg

    from app.config import database_url

    try:
        conn = psycopg.connect(database_url(), connect_timeout=3)
    except (RuntimeError, psycopg.OperationalError) as exc:
        pytest.skip(f"no database: {exc}")
    yield conn
    conn.close()
