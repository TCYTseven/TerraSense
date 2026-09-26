#!/usr/bin/env python3
"""Evaluate the avalanche model with a train/calibration/untouched-test year split."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.ml.avalanche_contract import MODEL_FEATURES, features_for_profile  # noqa: E402
from train_avalanche_model import SEED, apply_calibrator, fit_calibrator, metrics, model_params, select_threshold  # noqa: E402


def evaluate(table: pd.DataFrame, *, train_end_year: int, calibration_year: int, test_year: int, target_precision: float, feature_profile: str = "transferable", calibration_method: str = "auto") -> dict[str, Any]:
    table = table.copy()
    timestamps = pd.to_datetime(table["reference_timestamp"], utc=True, errors="raise")
    table["year"] = timestamps.dt.year
    labels = pd.to_numeric(table["label"], errors="raise").astype("int8")
    if "negative_eligible" in table:
        table = table.loc[(labels == 1) | table["negative_eligible"].fillna(False).astype(bool)].copy()
    for name in MODEL_FEATURES:
        table[name] = pd.to_numeric(table[name], errors="coerce")
    model_features = features_for_profile(feature_profile)
    train_mask = table["year"] <= train_end_year
    calibration_mask = table["year"] == calibration_year
    test_mask = table["year"] == test_year
    if not train_mask.any() or not calibration_mask.any() or not test_mask.any():
        raise ValueError("requested years do not produce non-empty train/calibration/test partitions")
    train_labels = table.loc[train_mask, "label"].to_numpy(dtype="int8")
    calibration_labels = table.loc[calibration_mask, "label"].to_numpy(dtype="int8")
    test_labels = table.loc[test_mask, "label"].to_numpy(dtype="int8")
    if any(np.unique(part).size < 2 for part in (train_labels, calibration_labels, test_labels)):
        raise ValueError("each temporal partition must contain both classes")
    model = lgb.LGBMClassifier(**model_params(train_labels, feature_profile)).fit(table.loc[train_mask, list(model_features)], train_labels)
    calibration_raw = model.predict_proba(table.loc[calibration_mask, list(model_features)])[:, 1]
    calibration = fit_calibrator(calibration_raw, calibration_labels, calibration_method)
    calibration_probability = apply_calibrator(calibration_raw, calibration)
    selection = select_threshold(calibration_labels, calibration_probability, target_precision)
    test_raw = model.predict_proba(table.loc[test_mask, list(model_features)])[:, 1]
    test_probability = apply_calibrator(test_raw, calibration)
    slope = pd.to_numeric(table.loc[test_mask, "slope_mean"], errors="coerce").to_numpy(dtype="float64")
    valid_slope = np.isfinite(slope)
    forecast_rows = int(table.get("forecast_available", pd.Series(0, index=table.index)).fillna(0).astype(bool).sum())
    forecast_sources = sorted(str(value) for value in table.get("forecast_source", pd.Series(dtype=str)).dropna().unique())
    forecast_groups = {
        "precipitation": ["forecast_rain_0_6h", "forecast_rain_0_12h", "forecast_rain_0_24h", "forecast_rain_0_48h", "forecast_rain_0_72h"],
        "snowfall": ["forecast_snowfall_0_72h", "forecast_snowfall_ensemble_mean", "forecast_snowfall_ensemble_spread"],
        "temperature": ["forecast_temp_min", "forecast_temp_max"],
        "wind": ["forecast_wind_max_kmh", "forecast_wind_loading_proxy"],
    }
    populated_groups = [group for group, columns in forecast_groups.items() if all(column in table and table[column].notna().all() for column in columns)]
    missing_groups = [group for group in forecast_groups if group not in populated_groups]
    if forecast_rows:
        limitations = [
            f"Historical as-of forecast rows are populated for {forecast_rows}/{len(table)} samples from {', '.join(forecast_sources) or 'an NOAA source'}.",
            f"Forecast groups populated in this run: {', '.join(populated_groups) or 'none'}; missing groups: {', '.join(missing_groups) or 'none'}.",
            "The field-observation negatives are local coverage-backed controls, not a complete avalanche inventory.",
        ]
    else:
        limitations = [
            "This table contains observed/reanalysis weather and no historical as-of forecast rows.",
            "This is a retrospective observed-weather proxy, not an operational forecast-conditioned evaluation.",
            "The field-observation negatives are local coverage-backed controls, not a complete avalanche inventory.",
        ]
    precision_operating_points: dict[str, Any] = {}
    for target in (0.60, 0.70, 0.80, 0.85):
        chosen = select_threshold(calibration_labels, calibration_probability, target)
        precision_operating_points[str(target)] = {
            "validation": chosen,
            "untouched_test": metrics(test_labels, test_probability, chosen.get("threshold")),
        }
    calibration_comparison: dict[str, Any] = {}
    for method in ("raw", "platt", "isotonic"):
        candidate = fit_calibrator(calibration_raw, calibration_labels, method)
        calibration_comparison[method] = {
            "object": candidate,
            "validation": metrics(calibration_labels, apply_calibrator(calibration_raw, candidate)),
            "untouched_test": metrics(test_labels, apply_calibrator(test_raw, candidate)),
        }
    return {
        "feature_profile": feature_profile,
        "feature_names": list(model_features),
        "partitions": {"train": int(train_mask.sum()), "calibration": int(calibration_mask.sum()), "test": int(test_mask.sum()), "test_positives": int(test_labels.sum())},
        "years": {"train_end": train_end_year, "calibration": calibration_year, "test": test_year},
        "test_prevalence_pr_baseline": round(float(test_labels.mean()), 6),
        "forecast_coverage": {"rows": forecast_rows, "fraction": round(forecast_rows / len(table), 6), "sources": forecast_sources},
        "train": metrics(train_labels, model.predict_proba(table.loc[train_mask, list(model_features)])[:, 1]),
        "calibration": metrics(calibration_labels, calibration_probability, selection.get("threshold")),
        "test_raw": metrics(test_labels, test_raw),
        "test_calibrated": metrics(test_labels, test_probability, selection.get("threshold")),
        "threshold_selection": selection,
        "precision_operating_points": precision_operating_points,
        "calibration_comparison": calibration_comparison,
        "calibration_object": calibration,
        "slope_only_test": {
            "roc_auc": None if not valid_slope.any() else round(float(roc_auc_score(test_labels[valid_slope], slope[valid_slope])), 6),
            "pr_auc": None if not valid_slope.any() else round(float(average_precision_score(test_labels[valid_slope], slope[valid_slope])), 6),
        },
        "limitations": limitations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", type=Path, default=REPO_ROOT / "data/processed/avalanche_nwac_observed_proxy.parquet")
    parser.add_argument("--train-end-year", type=int, default=2024)
    parser.add_argument("--calibration-year", type=int, default=2025)
    parser.add_argument("--test-year", type=int, default=2026)
    parser.add_argument("--target-precision", type=float, default=0.85)
    parser.add_argument("--feature-profile", choices=("transferable", "full"), default="transferable")
    parser.add_argument("--calibration-method", choices=("auto", "isotonic", "platt", "raw"), default="auto")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "ml/artifacts/avalanche/nwac_observed_proxy/temporal_evaluation.json")
    args = parser.parse_args()
    report = evaluate(pd.read_parquet(args.table), train_end_year=args.train_end_year, calibration_year=args.calibration_year, test_year=args.test_year, target_precision=args.target_precision, feature_profile=args.feature_profile, calibration_method=args.calibration_method)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
