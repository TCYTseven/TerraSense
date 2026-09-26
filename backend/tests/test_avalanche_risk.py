"""Backend contract tests for avalanche inference and its fail-closed behavior."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.ml.avalanche_inference import predict_location
from app.ml import avalanche_inference
from app.weather import HourlyRain


def _conditions(source: str = "fixture") -> HourlyRain:
    start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=24)
    times = [start + timedelta(hours=index) for index in range(100)]
    return HourlyRain(
        times=times,
        precipitation_mm=[1.0] * 100,
        now_index=24,
        source=source,
        fetched_at=datetime.now(UTC),
        temperature_c=[-4.0] * 100,
        snowfall_cm=[0.8] * 100,
        snow_depth_m=[1.2] * 100,
        wind_kmh=[25.0] * 100,
        wind_gust_kmh=[40.0] * 100,
        wind_direction_deg=[315.0] * 100,
        freezing_level_m=[1000.0] * 100,
    )


def test_reported_probability_floor_is_at_least_ten_percent() -> None:
    reported, applied, floor = avalanche_inference._reported_probability(0.02)

    assert reported == 0.10
    assert applied is True
    assert floor == 0.10


def test_missing_avalanche_artifact_fails_closed(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(avalanche_inference, "MODEL_PATH", tmp_path / "missing.model")
    result = predict_location(
        46.8523,
        -121.7603,
        conditions_override=_conditions(),
        static_override={"elevation_mean": 1800.0, "slope_mean": 34.0, "snow_ice_fraction": 0.8},
    )
    assert result.state == "UNCERTAIN"
    assert "MODEL_ARTIFACT_MISSING" in result.reason_codes


def test_out_of_domain_location_fails_closed() -> None:
    result = predict_location(39.0, -106.0, conditions_override=_conditions())
    assert result.state == "UNCERTAIN"
    assert "OUT_OF_DISTRIBUTION" in result.reason_codes


def test_avalanche_route_is_exposed_with_typed_response() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    schema = TestClient(app).get("/openapi.json").json()
    operation = schema["paths"]["/api/v1/avalanche-risk"]["post"]
    response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert response_ref.endswith("/AvalancheRiskPrediction")
