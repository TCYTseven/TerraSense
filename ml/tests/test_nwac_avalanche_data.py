from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "ml" / "scripts"))

from app.ml.avalanche_contract import MODEL_FEATURES  # noqa: E402
from prepare_nwac_avalanche_dataset import _feature_row  # noqa: E402


def _cell() -> pd.Series:
    values = {name: None for name in MODEL_FEATURES}
    values.update({
        "cell_id": "rainier-1",
        "latitude": 46.85,
        "longitude": -121.75,
        "elevation_mean": 2500.0,
        "slope_mean": 32.0,
        "slope_max": 45.0,
        "slope_p90": 38.0,
        "aspect_sin_mean": 0.0,
        "aspect_cos_mean": 1.0,
        "snow_ice_fraction": 0.5,
        "dem_available": 1.0,
    })
    return pd.Series(values)


def _weather() -> pd.DataFrame:
    times = pd.date_range("2026-01-01", periods=48, freq="h", tz="UTC")
    return pd.DataFrame({
        "timestamp": times,
        "precipitation_mm": 1.0,
        "snowfall_cm": 0.5,
        "snow_depth_m": 1.0,
        "temperature_c": -2.0,
        "wind_speed_kmh": 10.0,
        "wind_gust_kmh": 15.0,
        "wind_direction_deg": 180.0,
    })


def test_current_day_event_is_not_recent_activity_feature() -> None:
    reference = pd.Timestamp("2026-01-02T00:00:00Z")
    event = {"id": "same-day", "date": "2026-01-02", "location_point": {"lat": 46.85, "lng": -121.75}}
    row = _feature_row(
        latitude=46.85,
        longitude=-121.75,
        reference=reference,
        label=1,
        cell=_cell(),
        weather=_weather(),
        events=[event],
        coverage=0.85,
        positive_event_id="same-day",
        source_record_id="same-day",
        label_confidence="published",
    )
    assert row["recent_avalanche_count_7d"] == 0
    assert row["feature_asof"] <= reference.isoformat()


def test_quality_coverage_is_not_a_label_proxy() -> None:
    reference = pd.Timestamp("2026-01-02T00:00:00Z")
    common = {
        "latitude": 46.85,
        "longitude": -121.75,
        "reference": reference,
        "cell": _cell(),
        "weather": _weather(),
        "events": [],
        "coverage": 0.85,
        "positive_event_id": None,
        "source_record_id": "record",
    }
    positive = _feature_row(label=1, label_confidence="published", **common)
    negative = _feature_row(label=0, label_confidence="field_observation_no_avalanche", **common)
    assert positive["event_observation_coverage"] == negative["event_observation_coverage"] == 0.85
    assert set(MODEL_FEATURES) <= positive.keys()


def test_historical_forecast_rows_join_without_using_a_future_run() -> None:
    reference = pd.Timestamp("2026-01-02T00:00:00Z")
    forecast_times = pd.date_range(reference, periods=12, freq="6h", tz="UTC")
    forecast = pd.DataFrame({
        "forecast_timestamp": forecast_times,
        "forecast_initialization": reference - pd.Timedelta(hours=6),
        "forecast_precipitation_mm": 2.0,
        "forecast_snowfall_cm": None,
        "forecast_temperature_c": None,
        "forecast_wind_speed_kmh": None,
        "forecast_wind_gust_kmh": None,
        "forecast_wind_direction_deg": None,
        "forecast_snowfall_ensemble_mean": None,
        "forecast_snowfall_ensemble_p90": None,
        "forecast_snowfall_ensemble_p95": None,
        "forecast_snowfall_ensemble_spread": None,
        "forecast_exceedance_probability": None,
        "forecast_source": "NOAA_GEFS",
    })
    row = _feature_row(
        latitude=46.85,
        longitude=-121.75,
        reference=reference,
        label=0,
        cell=_cell(),
        weather=_weather(),
        events=[],
        coverage=0.85,
        positive_event_id=None,
        source_record_id="field",
        label_confidence="field_observation_no_avalanche",
        forecast=forecast,
    )
    assert row["forecast_available"] == 1.0
    assert row["forecast_rain_0_72h"] == 24.0
    assert row["forecast_age_hours"] == 6.0
