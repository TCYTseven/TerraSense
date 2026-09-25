"""Postgres connections: one-off connections for scripts, a pool for the API."""

import threading
from collections.abc import Iterator

import psycopg
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from app.config import database_url

# Seconds a request waits for a pooled connection. A down database fails fast instead of
# holding the request for psycopg's 30 s default.
POOL_TIMEOUT_S = 5

_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def connect() -> psycopg.Connection:
    """Open one connection to DATABASE_URL. Use it in a with block so it commits and closes."""
    return psycopg.connect(database_url())


def get_pool() -> ConnectionPool:
    """The API's pool, created on first use so /health works without a database.

    FastAPI runs sync dependencies on a thread pool, so creation is locked.
    """
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ConnectionPool(
                    database_url(),
                    min_size=1,
                    max_size=5,
                    timeout=POOL_TIMEOUT_S,
                    kwargs={"row_factory": dict_row},
                    # Hosted Postgres drops idle connections. Check each one before use.
                    check=ConnectionPool.check_connection,
                    open=True,
                )
    return _pool


def close_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


def get_conn() -> Iterator[psycopg.Connection[DictRow]]:
    """FastAPI dependency: a pooled connection that returns dict rows."""
    with get_pool().connection() as conn:
        yield conn
