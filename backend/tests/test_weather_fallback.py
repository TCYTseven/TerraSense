"""When Open-Meteo stops answering, a run reads the last good response or a named fixture, labeled."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app import weather

STORM = "backend/fixtures/open_meteo_storm.json"


def _payload() -> dict:
    start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=168)
    times = [(start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(264)]
    return {"hourly": {"time": times, "precipitation": [1.0] * len(times)}}


@pytest.fixture
def offline(monkeypatch, tmp_path):
    """Open-Meteo refuses every call. Caches start empty and the disk copy goes to tmp_path."""
    monkeypatch.delenv("OPEN_METEO_FIXTURE", raising=False)
    monkeypatch.delenv("OPEN_METEO_FALLBACK_FIXTURE", raising=False)
    monkeypatch.setattr(weather, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(weather, "_cache", {})
    monkeypatch.setattr(weather, "_payloads", {})

    def refuse(*_, **__):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(weather.httpx, "get", refuse)
    return tmp_path


def test_no_response_and_no_fallback_still_fails_clearly(offline):
    rain, why = weather.try_hourly_rain()
    assert rain is None and "did not answer" in why


def test_the_last_good_response_on_disk_is_served_and_labeled(offline):
    key = f"{weather.PEAK_LAT:.4f},{weather.PEAK_LON:.4f}"
    weather._disk_path(key).write_text(json.dumps(_payload()))
    rain, why = weather.try_hourly_rain()
    assert why is None and rain.source == weather.CACHED_SOURCE
    assert rain.total(-24, 0) == 24.0  # "now" is the current hour, not the hour it was saved


def test_a_named_fallback_fixture_is_loaded_as_a_fixture(offline, monkeypatch):
    monkeypatch.setenv("OPEN_METEO_FALLBACK_FIXTURE", STORM)
    rain, why = weather.try_hourly_rain()
    assert why is None and rain.source == "fixture"


def test_a_good_response_is_kept_for_later(monkeypatch, tmp_path):
    monkeypatch.delenv("OPEN_METEO_FIXTURE", raising=False)
    monkeypatch.setattr(weather, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(weather, "_cache", {})
    monkeypatch.setattr(weather, "_payloads", {})
    payload = _payload()
    monkeypatch.setattr(weather.httpx, "get",
                        lambda *_, **__: httpx.Response(200, json=payload, request=httpx.Request("GET", "http://x")))
    rain = weather.get_hourly_rain()
    assert rain.source == "open-meteo" and list(tmp_path.glob("*.json"))
