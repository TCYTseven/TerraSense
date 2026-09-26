#!/usr/bin/env python3
"""Train, calibrate, and select a high-risk threshold for the 72-hour classifier.

This is separate from ``train_susceptibility.py`` on purpose.  The old model answers where the
terrain is relatively susceptible; this model answers whether a rainfall-triggered event is
expected in the next 72 hours from a timestamped information set.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.ml.risk_contract import (  # noqa: E402
    DEFAULT_ABSTENTION_BAND,
    DEFAULT_OOD_THRESHOLD,
    DEFAULT_TARGET_PRECISION,
    MODEL_FEATURES,
    PREDICTION_HORIZON_HOURS,
    feature_groups,
    validate_feature_names,
)

DEFAULT_TABLE = REPO_ROOT / "data" / "processed" / "landslide_risk.parquet"
DEFAULT_ARTIFACTS = REPO_ROOT / "ml" / "artifacts"
MODEL_FILENAME = "landslide_risk_lgbm.txt"
METADATA_FILENAME = "risk_model.json"
CALIBRATION_FILENAME = "risk_calibration.json"
SEED = 47


def validate_table(table: pd.DataFrame) -> None:
    missing = [name for name in (*MODEL_FEATURES, "label", "cell_id", "reference_timestamp") if name not in table.columns]
    if missing:
        raise ValueError(f"risk table missing columns: {missing}")
    labels = set(table["label"].dropna().unique().tolist())
    if not labels <= {0, 1} or len(labels) < 2:
        raise ValueError(f"risk labels must contain both binary classes, got {sorted(labels)}")
    if table[["cell_id", "reference_timestamp"]].duplicated().any():
        raise ValueError("risk table contains duplicate (cell_id, reference_timestamp) samples")
    reference = pd.to_datetime(table["reference_timestamp"], utc=True, errors="coerce")
    if reference.isna().any():
        raise ValueError("risk table contains invalid reference_timestamp values")


def read_table(path: Path) -> pd.DataFrame:
    table = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)
    validate_table(table)
    return table


def split_spatiotemporal(table: pd.DataFrame) -> tuple[pd.Series, dict[str, Any]]:
    """Hold out a complete year and geographic blocks, keeping storm groups together."""
    years = sorted(pd.to_datetime(table["reference_timestamp"], utc=True).dt.year.unique().tolist())
    if len(years) < 2:
        raise ValueError("spatiotemporal validation needs at least two reference years")
    latest_year = years[-1]
    spatial_values = table["spatial_group"].astype(str) if "spatial_group" in table else table["cell_id"].astype(str)
    spatial_groups = sorted(spatial_values.unique())
    heldout_count = max(1, int(np.ceil(len(spatial_groups) * 0.20)))
    heldout_spatial = set(spatial_groups[-heldout_count:])
    candidate = (pd.to_datetime(table["reference_timestamp"], utc=True).dt.year == latest_year) | spatial_values.isin(heldout_spatial)

    # Storm/event groups may cover multiple neighboring rows. Remove the group from training
    # whenever one of its rows is in test, so a single storm cannot leak across the seam.
    groups = table.get("storm_group", table["reference_timestamp"].astype(str).str.slice(0, 10)).astype(str)
    heldout_storms = set(groups[candidate].tolist())
    is_test = candidate | groups.isin(heldout_storms)
    if is_test.all() or (~is_test).all():
        raise ValueError("spatiotemporal split did not leave train and test rows")
    if table.loc[is_test, "label"].nunique() < 2 or table.loc[~is_test, "label"].nunique() < 2:
        raise ValueError("spatiotemporal split must contain positives and negatives on both sides")
    return is_test, {
        "heldout_years": [latest_year],
        "heldout_spatial_groups": sorted(heldout_spatial),
        "heldout_storm_groups": sorted(heldout_storms),
    }


def expected_calibration_error(y_true: np.ndarray, probabilities: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = len(y_true)
    error = 0.0
    for lower, upper in zip(edges[:-1], edges[1:], strict=True):
        selected = (probabilities >= lower) & ((probabilities < upper) if upper < 1 else (probabilities <= upper))
        if selected.any():
            error += selected.mean() * abs(float(y_true[selected].mean()) - float(probabilities[selected].mean()))
    return round(float(error), 6)


def threshold_metrics(
    y_true: np.ndarray,
    probabilities: np.ndarray,
    threshold: float | None,
    reference_timestamps: pd.Series | None = None,
) -> dict[str, float | int | None]:
    if threshold is None:
        return {"threshold": None, "precision": None, "recall": None, "f1": None, "false_positive_rate": None, "false_alerts_per_1000_cells": None, "event_capture_rate": None, "alerts_per_day": None, "alerts": 0}
    predicted = probabilities >= threshold
    negatives = max(1, int((y_true == 0).sum()))
    alerts_per_day = None
    if reference_timestamps is not None and len(reference_timestamps):
        timestamps = pd.to_datetime(reference_timestamps, utc=True)
        days = max(1.0, (timestamps.max() - timestamps.min()).total_seconds() / 86_400 + 1.0)
        alerts_per_day = round(float(predicted.sum() / days), 6)
    return {
        "threshold": round(float(threshold), 6),
        "precision": round(float(precision_score(y_true, predicted, zero_division=0)), 6),
        "recall": round(float(recall_score(y_true, predicted, zero_division=0)), 6),
        "f1": round(float(f1_score(y_true, predicted, zero_division=0)), 6),
        "false_positive_rate": round(float(((predicted == 1) & (y_true == 0)).sum() / negatives), 6),
        "false_alerts_per_1000_cells": round(float(((predicted == 1) & (y_true == 0)).sum() / max(1, len(y_true)) * 1000), 6),
        "event_capture_rate": round(float(recall_score(y_true, predicted, zero_division=0)), 6),
        "alerts_per_day": alerts_per_day,
        "alerts": int(predicted.sum()),
    }


def select_threshold(
    y_true: np.ndarray,
    probabilities: np.ndarray,
    target_precision: float,
    reference_timestamps: pd.Series | None = None,
) -> dict[str, Any]:
    """Find the lowest validated threshold that reaches the target precision, if any."""
    precision, _, thresholds = precision_recall_curve(y_true, probabilities)
    candidates = sorted(set(float(value) for value in thresholds), reverse=False)
    chosen = None
    for threshold in candidates:
        metrics = threshold_metrics(y_true, probabilities, threshold, reference_timestamps)
        if metrics["alerts"] and metrics["precision"] is not None and metrics["precision"] >= target_precision:
            chosen = threshold
            break
    return {
        "target_precision": target_precision,
        "selected": threshold_metrics(y_true, probabilities, chosen, reference_timestamps),
        "targets": {
            str(target): threshold_metrics(
                y_true,
                probabilities,
                next((float(value) for value in candidates if threshold_metrics(y_true, probabilities, value, reference_timestamps)["precision"] >= target), None),
                reference_timestamps,
            )
            for target in (0.80, 0.85, 0.90)
        },
    }


def fit_calibrator(raw: np.ndarray, y_true: np.ndarray, preferred: str = "isotonic") -> dict[str, Any]:
    if preferred == "isotonic" and len(np.unique(raw)) >= 5:
        model = IsotonicRegression(out_of_bounds="clip").fit(raw, y_true)
        return {
            "method": "isotonic",
            "x_thresholds": model.X_thresholds_.tolist(),
            "y_thresholds": model.y_thresholds_.tolist(),
        }
    model = LogisticRegression(random_state=SEED).fit(raw.reshape(-1, 1), y_true)
    return {"method": "platt", "coef": float(model.coef_[0][0]), "intercept": float(model.intercept_[0])}


def apply_calibrator(raw: np.ndarray, calibration: dict[str, Any]) -> np.ndarray:
    if calibration["method"] == "isotonic":
        return np.interp(raw, calibration["x_thresholds"], calibration["y_thresholds"]).astype("float64")
    logit = calibration["coef"] * raw + calibration["intercept"]
    return (1.0 / (1.0 + np.exp(-np.clip(logit, -60, 60)))).astype("float64")


def feature_distribution(table: pd.DataFrame) -> dict[str, dict[str, float]]:
    distributions = {}
    for name in MODEL_FEATURES:
        values = pd.to_numeric(table[name], errors="coerce").dropna().to_numpy(dtype="float64")
        if len(values) == 0:
            distributions[name] = {"p01": None, "p99": None, "median": None}
        else:
            distributions[name] = {
                "p01": float(np.quantile(values, 0.01)),
                "p99": float(np.quantile(values, 0.99)),
                "median": float(np.median(values)),
            }
    return distributions


def ood_score(features: pd.DataFrame, distributions: dict[str, dict[str, float]]) -> np.ndarray:
    scores = np.zeros(len(features), dtype="float64")
    for name in MODEL_FEATURES:
        bounds = distributions.get(name, {})
        low, high = bounds.get("p01"), bounds.get("p99")
        if low is None or high is None:
            continue
        values = pd.to_numeric(features[name], errors="coerce").to_numpy(dtype="float64")
        scores += np.where(np.isnan(values) | (values < low) | (values > high), 1.0, 0.0)
    return scores / max(1, len(MODEL_FEATURES))


def evaluate(y_true: np.ndarray, probabilities: np.ndarray) -> dict[str, Any]:
    return {
        "roc_auc": round(float(roc_auc_score(y_true, probabilities)), 6),
        "pr_auc": round(float(average_precision_score(y_true, probabilities)), 6),
        "brier_score": round(float(brier_score_loss(y_true, probabilities)), 6),
        "ece": expected_calibration_error(y_true, probabilities),
        "prevalence": round(float(y_true.mean()), 6),
        "rows": int(len(y_true)),
        "positives": int(y_true.sum()),
    }


def _safe_evaluate(y_true: np.ndarray, probabilities: np.ndarray) -> dict[str, Any] | None:
    """Return slice metrics only when the slice supports binary discrimination."""
    if len(y_true) == 0 or len(np.unique(y_true)) < 2:
        return None
    return evaluate(y_true, probabilities)


def grouped_bootstrap_intervals(
    y_true: np.ndarray,
    probabilities: np.ndarray,
    groups: pd.Series,
    *,
    iterations: int = 200,
    seed: int = SEED,
) -> dict[str, dict[str, float]]:
    """Bootstrap rows by event/storm group, not individual pixels or overlapping samples."""
    unique_groups = groups.astype(str).to_numpy()
    group_values = np.unique(unique_groups)
    if len(group_values) < 2:
        return {}
    rng = np.random.default_rng(seed)
    metrics: dict[str, list[float]] = {"pr_auc": [], "roc_auc": [], "brier_score": []}
    for _ in range(iterations):
        selected_groups = rng.choice(group_values, size=len(group_values), replace=True)
        selected = np.concatenate([np.flatnonzero(unique_groups == group) for group in selected_groups])
        result = _safe_evaluate(y_true[selected], probabilities[selected])
        if result is None:
            continue
        for name in metrics:
            metrics[name].append(float(result[name]))
    return {
        name: {"lower": round(float(np.quantile(values, 0.025)), 6), "upper": round(float(np.quantile(values, 0.975)), 6)}
        for name, values in metrics.items() if values
    }


def slice_metrics(table: pd.DataFrame, probabilities: np.ndarray) -> dict[str, Any]:
    """Report honest subgroups when their source columns exist; mark unavailable slices explicitly."""
    result: dict[str, Any] = {}
    candidates: dict[str, pd.Series] = {}
    if "spatial_group" in table:
        candidates["region"] = table["spatial_group"].astype(str)
    candidates["year"] = pd.to_datetime(table["reference_timestamp"], utc=True).dt.year.astype(str)
    if "climate_regime" in table:
        candidates["climate_regime"] = table["climate_regime"].astype(str)
    else:
        result["by_climate_regime"] = {"status": "not_available_in_feature_table"}
    if "slope_mean" in table:
        candidates["slope_band"] = pd.cut(table["slope_mean"], bins=[-np.inf, 15, 30, np.inf], labels=["<15deg", "15-30deg", ">=30deg"]).astype("string")
    if "rain_72h" in table:
        candidates["rainfall_band"] = pd.cut(table["rain_72h"], bins=[-np.inf, 10, 50, 100, np.inf], labels=["<10mm", "10-50mm", "50-100mm", ">=100mm"]).astype("string")
    elif "forecast_rain_0_72h" in table:
        candidates["rainfall_band"] = pd.cut(table["forecast_rain_0_72h"], bins=[-np.inf, 10, 50, 100, np.inf], labels=["<10mm", "10-50mm", "50-100mm", ">=100mm"]).astype("string")
    for dimension, labels in candidates.items():
        result[f"by_{dimension}"] = {}
        for label in sorted(labels.dropna().unique().tolist()):
            selected = labels == label
            evaluated = _safe_evaluate(table.loc[selected, "label"].to_numpy(dtype="int8"), probabilities[selected.to_numpy()])
            if evaluated is not None:
                result[f"by_{dimension}"][str(label)] = evaluated
    return result


def train(
    table: pd.DataFrame,
    *,
    target_precision: float = DEFAULT_TARGET_PRECISION,
    model_mode: str = "long-history",
) -> tuple[lgb.LGBMClassifier, dict[str, Any], dict[str, Any]]:
    if model_mode not in {"modern", "long-history"}:
        raise ValueError("model_mode must be 'modern' or 'long-history'")
    validate_feature_names(list(MODEL_FEATURES))
    validate_table(table)
    is_test, split = split_spatiotemporal(table)
    train_table, test_table = table[~is_test], table[is_test]
    x_train = train_table[list(MODEL_FEATURES)]
    x_test = test_table[list(MODEL_FEATURES)]
    y_train = train_table["label"].to_numpy(dtype="int8")
    y_test = test_table["label"].to_numpy(dtype="int8")
    scale_pos_weight = max(1.0, float((y_train == 0).sum()) / max(1, int(y_train.sum())))
    params = {
        "n_estimators": 350,
        "learning_rate": 0.04,
        "num_leaves": 31,
        "min_child_samples": 20,
        "subsample": 0.85,
        "subsample_freq": 1,
        "colsample_bytree": 0.85,
        "scale_pos_weight": scale_pos_weight,
        "n_jobs": 1,
        "random_state": SEED,
        "verbosity": -1,
    }
    holdout = lgb.LGBMClassifier(**params).fit(x_train, y_train)
    raw = holdout.predict_proba(x_test)[:, 1]
    calibration = fit_calibrator(raw, y_test)
    calibrated = apply_calibrator(raw, calibration)
    selection = select_threshold(y_test, calibrated, target_precision, test_table["reference_timestamp"])
    metrics = {
        "model": "lightgbm",
        "prediction_target": f"rainfall-triggered landslide in cell during next {PREDICTION_HORIZON_HOURS} hours",
        "feature_groups": feature_groups(),
        "features": list(MODEL_FEATURES),
        "split": split,
        "train": evaluate(y_train, holdout.predict_proba(x_train)[:, 1]),
        "test": evaluate(y_test, calibrated),
        "threshold_selection": selection,
        "calibration": calibration,
        "hyperparameters": params,
        "training_date": datetime.now(UTC).isoformat(timespec="seconds"),
        "training_years": sorted(pd.to_datetime(table["reference_timestamp"], utc=True).dt.year.unique().tolist()),
        "negative_source_counts": table.loc[table["label"] == 0, "negative_source_type"].value_counts().to_dict()
        if "negative_source_type" in table else {},
        "limitations": [
            "metrics are grouped by event/storm and spatial-temporal holdout, not random pixels",
            "threshold is absent when validation cannot support the requested precision",
            "calibrated probabilities are valid only within the training data domain",
        ],
    }
    metrics["test_slices"] = slice_metrics(test_table, calibrated)
    bootstrap_groups = test_table.get(
        "storm_group",
        test_table.get("positive_event_id", test_table["reference_timestamp"].astype(str).str.slice(0, 10)),
    )
    metrics["test_confidence_intervals"] = grouped_bootstrap_intervals(y_test, calibrated, bootstrap_groups)
    final = lgb.LGBMClassifier(**params).fit(table[list(MODEL_FEATURES)], table["label"])
    distributions = feature_distribution(table)
    metadata = {
        "model_version": "risk-lgbm-v1",
        "feature_names": list(MODEL_FEATURES),
        "horizon_hours": PREDICTION_HORIZON_HOURS,
        "cell_size_m": 1000,
        "model_mode": model_mode,
        "target_precision": target_precision,
        "ood_threshold": DEFAULT_OOD_THRESHOLD,
        "abstention_band": DEFAULT_ABSTENTION_BAND,
        "selected_threshold": selection["selected"]["threshold"],
        "training_date": metrics["training_date"],
        "feature_distributions": distributions,
        "feature_missing_rates": {name: round(float(table[name].isna().mean()), 6) for name in MODEL_FEATURES},
        "validation": metrics,
    }
    return final, metadata, calibration


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", type=Path, default=DEFAULT_TABLE)
    parser.add_argument("--artifacts", type=Path, default=DEFAULT_ARTIFACTS)
    parser.add_argument("--target-precision", type=float, default=float(os.environ.get("LANDSLIDE_TARGET_PRECISION", DEFAULT_TARGET_PRECISION)))
    parser.add_argument("--model-mode", choices=("modern", "long-history"), default=os.environ.get("LANDSLIDE_MODEL_MODE", "long-history"))
    args = parser.parse_args()
    table = read_table(args.table)
    model, metadata, calibration = train(table, target_precision=args.target_precision, model_mode=args.model_mode)
    args.artifacts.mkdir(parents=True, exist_ok=True)
    model_path = args.artifacts / MODEL_FILENAME
    model.booster_.save_model(str(model_path.with_name(model_path.name + ".part")))
    model_path.with_name(model_path.name + ".part").replace(model_path)
    (args.artifacts / METADATA_FILENAME).write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    (args.artifacts / CALIBRATION_FILENAME).write_text(json.dumps(calibration, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "model": str(model_path),
        "selected_threshold": metadata["selected_threshold"],
        "test": metadata["validation"]["test"],
        "precision_targets": metadata["validation"]["threshold_selection"]["targets"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
