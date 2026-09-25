"""Postgres connections."""

import psycopg

from app.config import database_url


def connect() -> psycopg.Connection:
    """Open one connection to DATABASE_URL. Use it in a with block so it commits and closes."""
    return psycopg.connect(database_url())
