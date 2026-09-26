"""API contract and fail-closed behavior for the production risk classifier."""

import numpy as np
import pytest
from fastapi.testclient import TestClient
from rasterio.transform import rowcol
from rasterio.warp import transform as warp_transform

from app.main import app
from app.ml import probability as probability_seam
from app.ml import risk_inference
from app.ml.probability import ProbabilityMap
from app.risk import risk_level

from .conftest import storm_rain

PEAK = {"latitude": 46.8523, "longitude": -121.7603}
# A steep Wonderland Trail slope in the northwest of the box, and the Paradise meadows by the
# Skyline trailhead.
VALLEY = (46.90446, -121.90055)
MEADOW = (46.7865, -121.7365)


@pytest.fixture
def storm(monkeypatch):
    rain = storm_rain()
    monkeypatch.setattr(risk_inference, "try_hourly_rain", lambda *_args, **_kwargs: (rain, None))
    risk_inference._map_cache = None
    return rain


def post(body: dict) -> dict:
    response = TestClient(app).post("/api/v1/landslide-risk", json=body)
    assert response.status_code == 200
    return response.json()


def test_risk_endpoint_returns_uncertain_when_forecast_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(risk_inference, "try_hourly_rain", lambda *_args, **_kwargs: (None, "fixture unavailable"))

    payload = post(PEAK)

    assert payload["state"] == "UNCERTAIN"
    assert {"FORECAST_UNAVAILABLE", "WEATHER_FEED_UNAVAILABLE"} <= set(payload["reason_codes"])
    assert payload["calibrated_probability"] is None
    # No rain is never read as a dry, safe day.
    assert payload["probability"] is None and payload["probability_source"] is None
    assert payload["risk_level"] is None and payload["estimate"] is None


def test_risk_endpoint_rejects_out_of_domain_as_uncertain() -> None:
    payload = post({"latitude": 40.0, "longitude": -73.0})

    assert payload["state"] == "UNCERTAIN"
    assert "OUT_OF_DISTRIBUTION" in payload["reason_codes"]
    assert payload["probability"] is None


def test_risk_endpoint_does_not_guess_timezone_for_naive_timestamp() -> None:
    payload = post({**PEAK, "timestamp": "2026-01-01T00:00:00"})

    assert payload["state"] == "UNCERTAIN"
    assert "TIMESTAMP_ALIGNMENT_ERROR" in payload["reason_codes"]
    assert payload["probability"] is None


def test_without_a_calibrated_model_the_answer_is_the_model_b_estimate(storm) -> None:
    payload = post({"latitude": VALLEY[0], "longitude": VALLEY[1]})

    assert payload["state"] == "UNCERTAIN", "the estimate never becomes a classifier decision"
    assert payload["calibrated_probability"] is None
    assert payload["probability_source"] == "model_b_estimate"
    assert 0.0 <= payload["probability"] <= 1.0
    assert payload["risk_level"] == risk_level(payload["probability"])

    estimate = payload["estimate"]
    assert estimate["calibrated"] is False and estimate["method"] == probability_seam.MODEL_B_METHOD
    assert estimate["pixel_probability"] == payload["probability"]
    assert estimate["cell"]["size_m"] == 1000
    assert estimate["cell"]["mean"] <= estimate["cell"]["max"]
    assert estimate["rain"]["source"] == "fixture" and estimate["rain"]["next_72h_mm"] > 0
    assert [d["factor"] for d in estimate["drivers"]] == ["terrain", "forecast_rain", "antecedent_moisture"]
    assert {d["effect"] for d in estimate["drivers"]} <= {"raises", "lowers", "neutral"}


def test_the_estimate_is_the_heat_map_value_under_the_click(storm) -> None:
    grid = probability_seam.score(storm)
    for lat, lon in (VALLEY, MEADOW):
        (x,), (y,) = warp_transform("EPSG:4326", grid.crs, [lon], [lat])
        row, col = rowcol(grid.transform, x, y)
        payload = post({"latitude": lat, "longitude": lon})
        assert payload["probability"] == pytest.approx(float(grid.values[row, col]), abs=1e-4)


def test_a_storm_separates_steep_valleys_from_meadows(storm) -> None:
    valley = post({"latitude": VALLEY[0], "longitude": VALLEY[1]})
    meadow = post({"latitude": MEADOW[0], "longitude": MEADOW[1]})

    assert meadow["risk_level"] == "low"
    assert valley["risk_level"] == "extreme"

    def effect(payload: dict, factor: str) -> str:
        return next(d["effect"] for d in payload["estimate"]["drivers"] if d["factor"] == factor)

    assert effect(meadow, "terrain") == "lowers" and effect(valley, "terrain") == "raises"
    assert effect(meadow, "forecast_rain") == effect(valley, "forecast_rain") == "raises"


def test_missing_terrain_is_reported_not_guessed(storm, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(probability_seam, "SUSCEPTIBILITY_PATH", tmp_path / "missing.tif")

    payload = post(PEAK)

    assert payload["probability"] is None and payload["estimate"] is None
    assert "ESTIMATE_UNAVAILABLE" in payload["reason_codes"]


def test_a_spot_the_heat_map_leaves_blank_gets_no_number(storm) -> None:
    grid = probability_seam.score(storm)
    blank = ProbabilityMap(np.full_like(grid.values, np.nan), grid.transform, grid.crs, grid.method)

    prediction = risk_inference.predict_location(*VALLEY, rain_override=storm, probability_override=blank)

    assert prediction.probability is None and prediction.estimate is None
    assert "ESTIMATE_UNAVAILABLE" in prediction.reason_codes


def test_the_estimate_is_json_native(storm) -> None:
    prediction = risk_inference.predict_location(*VALLEY)
    for value in prediction.estimate["drivers"][0].values():
        assert not isinstance(value, np.generic)
    assert not isinstance(prediction.probability, np.generic)
