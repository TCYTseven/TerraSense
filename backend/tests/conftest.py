"""Shared test setup. Run from backend/: python -m pytest"""

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

STORM_FIXTURE = "backend/fixtures/open_meteo_storm.json"


def storm_rain():
    """The synthetic storm fixture, loaded without leaving OPEN_METEO_FIXTURE set."""
    from app.weather import get_hourly_rain

    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("OPEN_METEO_FIXTURE", STORM_FIXTURE)
        return get_hourly_rain()


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
