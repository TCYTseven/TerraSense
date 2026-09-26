"""Environment wiring for database targets."""

import pytest

from app.config import database_url, db_target


def test_db_target_defaults_to_local(monkeypatch):
    monkeypatch.delenv("DB", raising=False)
    assert db_target() == "LOCAL"


def test_database_url_picks_prod(monkeypatch):
    monkeypatch.setenv("DB", "PROD")
    monkeypatch.setenv("DATABASE_URL_PROD", "postgresql://prod")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert database_url() == "postgresql://prod"


def test_database_url_rejects_bad_db(monkeypatch):
    monkeypatch.setenv("DB", "staging")
    with pytest.raises(RuntimeError, match="LOCAL or PROD"):
        db_target()
