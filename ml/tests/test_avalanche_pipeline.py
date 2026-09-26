"""Contract and leakage tests for the parallel avalanche-risk pipeline."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "ml" / "scripts"))

from app.ml.avalanche_contract import MODEL_FEATURES, TRANSFERABLE_FEATURES  # noqa: E402
from app.ml.avalanche_features import avalanche_dynamic_features  # noqa: E402
from build_avalanche_dataset import _parse_bool, label_samples  # noqa: E402
from train_avalanche_model import select_threshold, train  # noqa: E402


def _hourly(start: datetime, count: int = 120) -> list[datetime]:
    return [start + timedelta(hours=index) for index in range(count)]


def test_avalanche_past_features_ignore_values_after_reference() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    times = _hourly(start)
    reference = start + timedelta(hours=72)
    snowfall = [0.5] * len(times)
    changed = snowfall[:73] + [50.0] * (len(times) - 73)
    common = {
        "times": times,
        "reference_time": reference,
        "precipitation_mm": [1.0] * len(times),
        "snow_depth_m": [1.0] * len(times),
        "temperature_c": [-4.0] * len(times),
        "wind_speed_kmh": [20.0] * len(times),
        "forecast_times": times,
        "forecast_precipitation_mm": [1.0] * len(times),
        "forecast_temperature_c": [-4.0] * len(times),
        "forecast_wind_speed_kmh": [20.0] * len(times),
    }
    common["forecast_snowfall_cm"] = [2.0] * len(times)
    before = avalanche_dynamic_features(snowfall_cm=snowfall, **common)
    after = avalanche_dynamic_features(snowfall_cm=changed, **common)
    assert before["new_snow_72h_cm"] == after["new_snow_72h_cm"]
    assert before["forecast_snowfall_0_72h"] == after["forecast_snowfall_0_72h"]
    changed_forecast = avalanche_dynamic_features(
        snowfall_cm=snowfall,
        **{**common, "forecast_snowfall_cm": changed},
    )
    assert before["forecast_snowfall_0_72h"] != changed_forecast["forecast_snowfall_0_72h"]


def test_avalanche_label_is_only_inside_next_24_hours() -> None:
    reference = datetime(2026, 1, 1, tzinfo=UTC)
    samples = pd.DataFrame([
        {"cell_id": "1:1", "reference_timestamp": reference.isoformat(), "feature_asof": reference.isoformat()},
        {"cell_id": "1:1", "reference_timestamp": (reference + timedelta(hours=1)).isoformat(), "feature_asof": reference.isoformat()},
    ])
    events = pd.DataFrame([{
        "cell_id": "1:1",
        "event_id": "avalanche-1",
        "event_timestamp": reference + timedelta(hours=23),
        "verified": True,
    }])
    labeled = label_samples(samples, events)
    assert labeled["label"].tolist() == [1, 1]
    events.loc[0, "event_timestamp"] = reference + timedelta(hours=25)
    assert label_samples(samples, events)["label"].tolist() == [0, 0]


def test_event_verification_parsing_does_not_treat_false_as_true() -> None:
    assert _parse_bool("false") is False
    assert _parse_bool("true") is True


def test_unknown_absence_requires_coverage_to_become_negative() -> None:
    samples = pd.DataFrame([
        {"cell_id": "1:1", "reference_timestamp": "2026-01-01T00:00:00Z", "event_observation_coverage": 0.79},
        {"cell_id": "1:2", "reference_timestamp": "2026-01-01T00:00:00Z", "event_observation_coverage": 0.80},
    ])
    labeled = label_samples(samples, pd.DataFrame())
    assert labeled["negative_eligible"].tolist() == [False, True]


def test_threshold_refuses_unproven_precision() -> None:
    selection = select_threshold(np.array([0, 0, 1, 1]), np.array([0.1, 0.2, 0.3, 0.4]), 1.01)
    assert selection["threshold"] is None
    assert selection["reachable"] is False


def test_avalanche_training_persists_all_feature_groups_and_calibration() -> None:
    rows = []
    for region_index, region in enumerate(("north", "south")):
        for index in range(40):
            label = int(index % 4 == 0)
            row = {name: float(index + label * 3 + region_index * 0.1) for name in MODEL_FEATURES}
            row.update({
                "label": label,
                "cell_id": f"{region_index}:{index}",
                "region": region,
                "reference_timestamp": f"2024-{(index % 9) + 1:02d}-01T00:00:00Z",
                "label_confidence": "high" if label else "high_negative",
                "negative_eligible": True,
            })
            rows.append(row)
    model, metadata, calibration = train(pd.DataFrame(rows), target_precision=0.80)
    assert model.booster_.num_trees() > 0
    assert metadata["prediction_target"].startswith("avalanche occurrence")
    assert metadata["validation"]["prevalence"] > 0
    assert calibration["method"] in {"isotonic", "platt", "raw"}


def test_transferable_profile_is_a_canonical_subset() -> None:
    assert len(TRANSFERABLE_FEATURES) < len(MODEL_FEATURES)
    assert set(TRANSFERABLE_FEATURES).issubset(set(MODEL_FEATURES))


def test_explicit_temporal_training_does_not_fit_final_model_on_test_year() -> None:
    rows = []
    for year in (2024, 2025, 2026):
        for index in range(12):
            label = int(index % 3 == 0)
            row = {name: float(index + label * 3) for name in MODEL_FEATURES}
            row.update({
                "label": label,
                "cell_id": f"cell:{index}",
                "region": "rainier",
                "reference_timestamp": f"{year}-01-{index + 1:02d}T00:00:00Z",
                "label_confidence": "high",
                "negative_eligible": True,
            })
            rows.append(row)
    _, metadata, calibration = train(
        pd.DataFrame(rows),
        target_precision=0.80,
        train_end_year=2024,
        calibration_year=2025,
    )
    assert metadata["split"]["strategy"] == "explicit-temporal-calibration"
    assert metadata["training_years"] == [2024, 2025]
    assert metadata["held_out_years"] == [2026]
    assert calibration["fitted_on"] == 12


def test_unknown_absence_is_not_a_safe_negative_by_default() -> None:
    rows = []
    for index in range(4):
        row = {name: float(index) for name in MODEL_FEATURES}
        row.update({
            "label": int(index == 0),
            "cell_id": str(index),
            "region": "north",
            "reference_timestamp": f"2024-01-{index + 1:02d}T00:00:00Z",
            "label_confidence": "high" if index == 0 else "unknown_absence",
            "negative_eligible": index == 0,
        })
        rows.append(row)
    try:
        train(pd.DataFrame(rows), target_precision=0.80)
    except ValueError as error:
        assert "both positive and negative" in str(error)
    else:
        raise AssertionError("unknown absences must not silently become negative labels")
