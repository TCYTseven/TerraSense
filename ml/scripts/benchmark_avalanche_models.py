#!/usr/bin/env python3
"""Leakage-safe benchmark for avalanche feature profiles and model complexity.

The 2026 partition is never used to select a profile, tree depth, calibration method, or
threshold.  Candidates are ranked on the 2025 calibration year, then the selected candidate is
reported once on the untouched 2026 year.  The script is intentionally small and deterministic:
it is a guard against overfitting a 173-row mountain-specific table.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.ml.avalanche_contract import (  # noqa: E402
    FORECAST_FEATURES,
    MODEL_FEATURES,
    SNOWPACK_FEATURES,
    STATIC_FEATURES,
    TRANSFERABLE_FEATURES,
)
from train_avalanche_model import SEED, ece, metrics, model_params  # noqa: E402


def _active(table: pd.DataFrame, train_mask: pd.Series, names: tuple[str, ...]) -> list[str]:
    """Drop only all-missing/constant columns as observed in training, never using test labels."""
    active: list[str] = []
    for name in names:
        values = pd.to_numeric(table.loc[train_mask, name], errors="coerce")
        if values.notna().any() and values.nunique(dropna=True) > 1:
            active.append(name)
    return active


def _specs() -> dict[str, tuple[str, ...]]:
    return {
        "slope_only": ("slope_mean",),
        "logistic_transferable": TRANSFERABLE_FEATURES,
        "lgbm_transferable": TRANSFERABLE_FEATURES,
        "lgbm_full_current": MODEL_FEATURES,
        "lgbm_observed": (*STATIC_FEATURES, *SNOWPACK_FEATURES),
        "lgbm_forecast": FORECAST_FEATURES,
    }


def _fit_predict(name: str, frame: pd.DataFrame, train_mask: pd.Series, score_mask: pd.Series, names: tuple[str, ...]) -> np.ndarray:
    y_train = frame.loc[train_mask, "label"].to_numpy(dtype="int8")
    active = _active(frame, train_mask, names)
    if name == "slope_only":
        return pd.to_numeric(frame.loc[score_mask, "slope_mean"], errors="coerce").fillna(float(frame.loc[train_mask, "slope_mean"].median())).to_numpy(dtype="float64")
    if name == "logistic_transferable":
        model = make_pipeline(
            SimpleImputer(strategy="median", add_indicator=True),
            StandardScaler(),
            LogisticRegression(C=1.0, class_weight="balanced", max_iter=3000, random_state=SEED),
        )
        model.fit(frame.loc[train_mask, active], y_train)
    else:
        profile = "full" if name == "lgbm_full_current" else "transferable"
        params = model_params(y_train, profile)
        model = lgb.LGBMClassifier(**params).fit(frame.loc[train_mask, active], y_train)
    return model.predict_proba(frame.loc[score_mask, active])[:, 1]


def _metric(labels: np.ndarray, probabilities: np.ndarray, *, probabilistic: bool = True) -> dict[str, Any]:
    return {
        "rows": int(len(labels)),
        "positives": int(labels.sum()),
        "prevalence": round(float(labels.mean()), 6),
        "pr_auc": round(float(average_precision_score(labels, probabilities)), 6),
        "pr_lift": round(float(average_precision_score(labels, probabilities) / labels.mean()), 6),
        "roc_auc": round(float(roc_auc_score(labels, probabilities)), 6),
        "brier_score": round(float(brier_score_loss(labels, probabilities)), 6) if probabilistic else None,
        "ece": ece(labels, probabilities) if probabilistic else None,
    }


def benchmark(table: pd.DataFrame, *, train_end_year: int = 2024, calibration_year: int = 2025, test_year: int = 2026) -> dict[str, Any]:
    frame = table.copy()
    frame["year"] = pd.to_datetime(frame["reference_timestamp"], utc=True).dt.year
    labels = pd.to_numeric(frame["label"], errors="raise").astype("int8")
    if "negative_eligible" in frame:
        frame = frame.loc[(labels == 1) | frame["negative_eligible"].fillna(False).astype(bool)].copy()
    for name in MODEL_FEATURES:
        frame[name] = pd.to_numeric(frame[name], errors="coerce")
    train_mask = frame["year"] <= train_end_year
    validation_mask = frame["year"] == calibration_year
    test_mask = frame["year"] == test_year
    if any(not mask.any() for mask in (train_mask, validation_mask, test_mask)):
        raise ValueError("benchmark requires non-empty train, validation, and untouched test years")
    y_validation = frame.loc[validation_mask, "label"].to_numpy(dtype="int8")
    y_test = frame.loc[test_mask, "label"].to_numpy(dtype="int8")
    rows: list[dict[str, Any]] = []
    for name, names in _specs().items():
        validation_probability = _fit_predict(name, frame, train_mask, validation_mask, names)
        test_probability = _fit_predict(name, frame, train_mask, test_mask, names)
        is_probability = name != "slope_only"
        rows.append({
            "candidate": name,
            "feature_count": len(_active(frame, train_mask, names)),
            "validation": _metric(y_validation, validation_probability, probabilistic=is_probability),
            "untouched_test": _metric(y_test, test_probability, probabilistic=is_probability),
        })
    # The test partition is only reported; this is the sole selection rule.
    selected = max(rows, key=lambda row: (row["validation"]["pr_auc"], -(row["validation"]["brier_score"] if row["validation"]["brier_score"] is not None else 1.0), -row["feature_count"]))
    selected_name = selected["candidate"]
    selected_names = _specs()[selected_name]
    raw_validation = _fit_predict(selected_name, frame, train_mask, validation_mask, selected_names)
    raw_test = _fit_predict(selected_name, frame, train_mask, test_mask, selected_names)
    rolling: list[dict[str, Any]] = []
    years = sorted(int(year) for year in frame["year"].unique())
    for rolling_test_year in years[1:]:
        rolling_train = frame["year"] < rolling_test_year
        rolling_test = frame["year"] == rolling_test_year
        rolling_labels = frame.loc[rolling_test, "label"].to_numpy(dtype="int8")
        if rolling_labels.size == 0 or np.unique(frame.loc[rolling_train, "label"]).size < 2:
            continue
        for name, names in _specs().items():
            score = _fit_predict(name, frame, rolling_train, rolling_test, names)
            rolling.append({"test_year": rolling_test_year, "candidate": name, "metrics": _metric(rolling_labels, score, probabilistic=name != "slope_only")})
    rolling_summary: list[dict[str, Any]] = []
    for name in _specs():
        values = [row["metrics"]["roc_auc"] for row in rolling if row["candidate"] == name]
        pr_values = [row["metrics"]["pr_auc"] for row in rolling if row["candidate"] == name]
        if values:
            rolling_summary.append({
                "candidate": name,
                "folds": len(values),
                "roc_auc_mean": round(float(np.mean(values)), 6),
                "roc_auc_median": round(float(np.median(values)), 6),
                "pr_auc_mean": round(float(np.mean(pr_values)), 6),
                "pr_auc_median": round(float(np.median(pr_values)), 6),
            })

    return {
        "seed": SEED,
        "selection_rule": "highest validation PR-AUC, then lowest validation Brier, then fewest active features",
        "partitions": {"train_end_year": train_end_year, "calibration_year": calibration_year, "untouched_test_year": test_year, "train_rows": int(train_mask.sum()), "validation_rows": int(validation_mask.sum()), "test_rows": int(test_mask.sum())},
        "test_prevalence_pr_baseline": round(float(y_test.mean()), 6),
        "candidates": rows,
        "selected_candidate": selected_name,
        "selected_validation": _metric(y_validation, raw_validation, probabilistic=selected_name != "slope_only"),
        "selected_untouched_test": _metric(y_test, raw_test, probabilistic=selected_name != "slope_only"),
        "rolling_origin_results": rolling,
        "rolling_origin_summary": rolling_summary,
        "note": "All candidate test numbers are held-out reports. No candidate, threshold, or calibrator was selected from the untouched test year.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", type=Path, default=REPO_ROOT / "data/processed/avalanche_nwac_gefs_all.parquet")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "ml/artifacts/avalanche/nwac_gefs_all/model_benchmark.json")
    args = parser.parse_args()
    report = benchmark(pd.read_parquet(args.table))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
