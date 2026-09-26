"""Tests for the timestamped, calibrated risk pipeline contract."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "ml" / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "backend"))

import build_risk_dataset as dataset  # noqa: E402
import backtest_risk_model as backtest  # noqa: E402
import build_risk_samples as samples  # noqa: E402
import train_risk_model as training  # noqa: E402
from app.ml.risk_contract import MODEL_FEATURES  # noqa: E402
from app.ml.risk_features import hourly_dynamic_features  # noqa: E402


def test_rainfall_features_do_not_change_when_observed_future_is_changed() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    times = [start + timedelta(hours=index) for index in range(96)]
    precipitation = [1.0] * 96
    changed = precipitation[:49] + [100.0] * 47
    reference = start + timedelta(hours=48)

    before = hourly_dynamic_features(times, precipitation, reference, forecast_times=times, forecast_precipitation_mm=precipitation)
    after = hourly_dynamic_features(times, changed, reference, forecast_times=times, forecast_precipitation_mm=changed)

    assert before["rain_24h"] == after["rain_24h"]
    assert before["rain_72h"] == after["rain_72h"]
    assert before["forecast_rain_0_72h"] != after["forecast_rain_0_72h"]


def test_label_builder_filters_unknown_and_non_rainfall_events(tmp_path: Path) -> None:
    path = tmp_path / "events.geojson"
    path.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "id": "rain", "geometry": {"type": "Point", "coordinates": [-121.7, 46.85]},
             "properties": {"catalog": "NASA COOLR / Global Landslide Catalog", "date": "2026-01-02", "trigger": "downpour", "location_accuracy": "exact"}},
            {"type": "Feature", "id": "quake", "geometry": {"type": "Point", "coordinates": [-121.7, 46.85]},
             "properties": {"catalog": "USGS Inventories v3", "date": "2026-01-02", "trigger": "earthquake", "location_accuracy": "exact"}},
            {"type": "Feature", "id": "unknown", "geometry": {"type": "Point", "coordinates": [-121.7, 46.85]},
             "properties": {"catalog": "USGS Inventories v3", "trigger": "rainfall", "location_accuracy": "unknown"}},
        ],
    }), encoding="utf-8")

    events = dataset.read_events(path)

    assert [event.event_id for event in events] == ["rain"]
    assert events[0].timestamp_uncertainty_days == 0


def test_label_builder_accepts_nasa_glc_csv_export(tmp_path: Path) -> None:
    path = tmp_path / "nasa.csv"
    path.write_text(
        "event_id,event_date,landslide_trigger,longitude,latitude,source_link,location_accuracy\n"
        "rain-1,01/02/2026,rain,-121.7,46.85,https://example.test/rain,exact\n"
        "quake-1,01/02/2026,earthquake,-121.7,46.85,https://example.test/quake,exact\n",
        encoding="utf-8",
    )

    events = dataset.read_events(path)

    assert [event.event_id for event in events] == ["rain-1"]
    assert events[0].dataset == "NASA COOLR / Global Landslide Catalog"


def test_future_asof_is_rejected() -> None:
    frame = pd.DataFrame({
        "reference_timestamp": ["2026-01-01T00:00:00Z"],
        "feature_asof": ["2026-01-01T01:00:00Z"],
    })
    with pytest.raises(ValueError, match="future-data leakage"):
        dataset.assert_no_future_leakage(frame)


def test_negative_sampling_tags_only_observed_hard_and_susceptible_candidates() -> None:
    frame = pd.DataFrame([
        {"label": 1, "cell_id": "10:10", "storm_group": "storm-a", "slope_mean": 30},
        {"label": 0, "cell_id": "11:11", "storm_group": "storm-a", "slope_mean": 28},
        {"label": 0, "cell_id": "40:40", "storm_group": "storm-b", "slope_mean": 45},
        {"label": 0, "cell_id": "80:80", "storm_group": "storm-c", "slope_mean": 2},
    ])

    tagged = dataset.assign_negative_source(frame)

    assert tagged.loc[1, "negative_source_type"] == "storm_matched_hard_negative"
    assert tagged.loc[1, "negative_confidence"] == "medium"
    assert set(tagged.loc[tagged["label"] == 0, "negative_source_type"]) <= {
        "storm_matched_hard_negative",
        "susceptible_terrain_negative",
        "background",
    }


def _training_table() -> pd.DataFrame:
    rows = []
    for year in range(2020, 2024):
        for index in range(30):
            label = int(index % 4 == 0 or index == 7)
            row = {name: float(index + label * 2) for name in MODEL_FEATURES}
            row.update({
                "label": label,
                "cell_id": f"{index % 6}:{index // 6}",
                "spatial_group": index % 6,
                "storm_group": f"{year}-{index}",
                "reference_timestamp": f"{year}-06-{(index % 9) + 1:02d}T00:00:00Z",
                "negative_source_type": "background" if not label else "positive_event",
            })
            rows.append(row)
    return pd.DataFrame(rows)


def test_training_is_spatiotemporal_and_persists_calibration_contract() -> None:
    table = _training_table()
    model, metadata, calibration = training.train(table, target_precision=0.80)

    assert metadata["horizon_hours"] == 72
    assert metadata["cell_size_m"] == 1000
    assert metadata["validation"]["test"]["pr_auc"] >= 0
    assert calibration["method"] in {"isotonic", "platt"}
    assert metadata["selected_threshold"] is None or 0 <= metadata["selected_threshold"] <= 1
    scores = model.predict_proba(table[list(MODEL_FEATURES)])[:, 1]
    assert np.isfinite(scores).all()


def test_backtest_reuses_calibration_and_marks_states() -> None:
    table = _training_table()
    model, metadata, calibration = training.train(table, target_precision=0.80)

    predictions, report = backtest.run_backtest(table, model.booster_, calibration, metadata)

    assert len(predictions) == len(table)
    assert set(predictions["state"]) <= {"HIGH_RISK", "NOT_HIGH_RISK", "UNCERTAIN"}
    assert report["calibration_method"] == calibration["method"]
    assert report["metrics"]["pr_auc"] >= 0


def test_threshold_reports_insufficient_evidence() -> None:
    y = np.array([0, 0, 0, 1])
    probabilities = np.array([0.1, 0.2, 0.3, 0.4])
    selection = training.select_threshold(y, probabilities, target_precision=1.01)

    assert selection["selected"]["threshold"] is None


def test_sample_builder_never_uses_a_forecast_initialized_after_reference() -> None:
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    rows = []
    for hour in range(96):
        timestamp = start + pd.Timedelta(hours=hour)
        rows.append({
            "timestamp": timestamp,
            "latitude": 46.8,
            "longitude": -121.7,
            "cell_id": "1:2",
            "precipitation_mm": 1.0,
            "is_forecast": False,
        })
    for hour in range(1, 73):
        rows.append({
            "timestamp": start + pd.Timedelta(hours=hour),
            "latitude": 46.8,
            "longitude": -121.7,
            "cell_id": "1:2",
            "precipitation_mm": 2.0,
            "is_forecast": True,
            "forecast_initialization": start,
        })
    frame = samples.build_samples(pd.DataFrame(rows), reference_stride_hours=24)

    assert not frame.empty
    init = pd.to_datetime(frame["forecast_initialization"], utc=True)
    reference = pd.to_datetime(frame["reference_timestamp"], utc=True)
    assert (init[init.notna()] <= reference[init.notna()]).all()
