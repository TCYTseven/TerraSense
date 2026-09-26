"""API contract and fail-closed behavior for the production risk classifier."""

from fastapi.testclient import TestClient

from app.main import app
from app.ml import risk_inference


def test_risk_endpoint_returns_uncertain_when_forecast_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(risk_inference, "try_hourly_rain", lambda *_args, **_kwargs: (None, "fixture unavailable"))

    response = TestClient(app).post("/api/v1/landslide-risk", json={"latitude": 46.8523, "longitude": -121.7603})

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "UNCERTAIN"
    assert "FORECAST_UNAVAILABLE" in payload["reason_codes"]
    assert payload["calibrated_probability"] is None


def test_risk_endpoint_rejects_out_of_domain_as_uncertain() -> None:
    response = TestClient(app).post("/api/v1/landslide-risk", json={"latitude": 40.0, "longitude": -73.0})

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "UNCERTAIN"
    assert "OUT_OF_DISTRIBUTION" in payload["reason_codes"]


def test_risk_endpoint_does_not_guess_timezone_for_naive_timestamp() -> None:
    response = TestClient(app).post(
        "/api/v1/landslide-risk",
        json={"latitude": 46.8523, "longitude": -121.7603, "timestamp": "2026-01-01T00:00:00"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "UNCERTAIN"
    assert "TIMESTAMP_ALIGNMENT_ERROR" in payload["reason_codes"]
