#!/usr/bin/env python3
"""Train and calibrate the avalanche next-24-hour classifier.

LightGBM is used because the feature table mixes nonlinear snow-loading thresholds, circular
terrain proxies, missing observations, and optional weak-layer/field-report features.  The script
uses a deterministic region/year holdout, calibrates only on that holdout, and refuses to invent a
high-risk threshold when the requested precision is not demonstrated.
"""

from __future__ import annotations

import argparse
import json
import os
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
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)

import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.ml.avalanche_contract import (  # noqa: E402
    DEFAULT_ABSTENTION_BAND,
    DEFAULT_MIN_NEGATIVE_COVERAGE,
    DEFAULT_OOD_THRESHOLD,
    DEFAULT_TARGET_PRECISION,
    MODEL_FEATURES,
    PREDICTION_HORIZON_HOURS,
    features_for_profile,
    feature_groups,
    validate_feature_names,
)

SEED = 41
ISOTONIC_MIN_SAMPLES = 80
DEFAULT_TABLE = REPO_ROOT / "data" / "processed" / "avalanche_risk.parquet"
DEFAULT_ARTIFACTS = REPO_ROOT / "ml" / "artifacts" / "avalanche"
MODEL_FILENAME = "avalanche_lgbm.model"
METADATA_FILENAME = "avalanche_model.json"
CALIBRATION_FILENAME = "avalanche_calibration.json"


def read_table(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)


def validate_table(table: pd.DataFrame) -> None:
    missing = sorted(set(MODEL_FEATURES) - set(table.columns))
    required = {"label", "reference_timestamp", "region", "cell_id"}
    missing += sorted(required - set(table.columns))
    if missing:
        raise ValueError(f"avalanche table missing required columns: {sorted(set(missing))}")
    labels = pd.to_numeric(table["label"], errors="raise").astype(int)
    if not set(labels.unique()) <= {0, 1} or labels.nunique() < 2:
        raise ValueError("avalanche table needs both positive and negative labels")
    timestamps = pd.to_datetime(table["reference_timestamp"], utc=True, errors="raise")
    if timestamps.isna().any():
        raise ValueError("reference_timestamp contains null values")


def _safe_metric(fn, labels: np.ndarray, scores: np.ndarray) -> float | None:
    if len(labels) == 0 or len(np.unique(labels)) < 2:
        return None
    return round(float(fn(labels, scores)), 6)


def ece(labels: np.ndarray, probabilities: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = 0.0
    for left, right in zip(edges[:-1], edges[1:], strict=False):
        selected = (probabilities >= left) & (probabilities < right if right < 1 else probabilities <= right)
        if selected.any():
            total += float(selected.mean()) * abs(float(probabilities[selected].mean()) - float(labels[selected].mean()))
    return round(total, 6)


def metrics(labels: np.ndarray, probabilities: np.ndarray, threshold: float | None = None) -> dict[str, Any]:
    prevalence = float(labels.mean()) if len(labels) else None
    pr_auc = _safe_metric(average_precision_score, labels, probabilities)
    result: dict[str, Any] = {
        "rows": int(len(labels)),
        "positives": int(labels.sum()),
        "prevalence": None if prevalence is None else round(prevalence, 6),
        "pr_auc": pr_auc,
        "pr_lift": None if pr_auc is None or not prevalence else round(float(pr_auc) / prevalence, 6),
        "roc_auc": _safe_metric(roc_auc_score, labels, probabilities),
        "brier_score": round(float(brier_score_loss(labels, probabilities)), 6) if len(labels) else None,
        "ece": ece(labels, probabilities) if len(labels) else None,
    }
    if threshold is not None:
        predicted = (probabilities >= threshold).astype(int)
        matrix = confusion_matrix(labels, predicted, labels=[0, 1]).tolist()
        result.update({
            "threshold": round(float(threshold), 6),
            "precision": round(float(precision_score(labels, predicted, zero_division=0)), 6),
            "recall": round(float(recall_score(labels, predicted, zero_division=0)), 6),
            "f1": round(float(f1_score(labels, predicted, zero_division=0)), 6),
            "confusion_matrix": matrix,
        })
    return result


def split_spatiotemporal(table: pd.DataFrame) -> tuple[pd.Series, dict[str, Any]]:
    """Prefer a complete geographic holdout; fall back to a complete latest winter."""
    regions = sorted(table["region"].astype(str).unique())
    timestamps = pd.to_datetime(table["reference_timestamp"], utc=True)
    years = sorted(timestamps.dt.year.unique().tolist())
    holdout_region = regions[-1]
    test = table["region"].astype(str) == holdout_region
    strategy = "leave-one-region-out"
    # A Rainier-only training table often has one geographic tile.  Do not select the
    # only region as a holdout; fall back to a complete latest year instead.
    if test.all() or test.sum() < 10 or table.loc[test, "label"].nunique() < 2:
        holdout_year = years[-1]
        test = timestamps.dt.year == holdout_year
        strategy = "latest-year"
    if test.sum() < 10 or table.loc[test, "label"].nunique() < 2:
        order = np.argsort(timestamps.astype("int64").to_numpy())
        test = pd.Series(False, index=table.index)
        test.iloc[order[-max(10, len(order) // 5):]] = True
        strategy = "latest-time-fallback"
    if test.all() or (~test).sum() < 2:
        raise ValueError("not enough rows for an avalanche train/validation split")
    return test, {
        "strategy": strategy,
        "holdout_region": holdout_region,
        "holdout_years": sorted(timestamps.loc[test].dt.year.unique().tolist()),
        "train_regions": sorted(table.loc[~test, "region"].astype(str).unique().tolist()),
        "validation_regions": sorted(table.loc[test, "region"].astype(str).unique().tolist()),
    }


def fit_calibrator(raw: np.ndarray, labels: np.ndarray, preferred: str = "auto") -> dict[str, Any]:
    if len(np.unique(labels)) < 2:
        return {"method": "raw", "fitted_on": int(len(labels)), "reason": "validation has one class"}
    if preferred == "raw":
        return {"method": "raw", "fitted_on": int(len(labels)), "reason": "explicitly disabled"}
    # Isotonic is flexible but high variance on the small validation sets available for a
    # single mountain. Keep it available for larger validation sets; use regularized Platt
    # scaling for small samples so calibration does not destroy ranking.
    use_isotonic = (
        preferred == "isotonic" and len(np.unique(raw)) >= 8
    ) or (
        preferred == "auto" and len(labels) >= ISOTONIC_MIN_SAMPLES and len(np.unique(raw)) >= 8
    )
    if use_isotonic:
        model = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(raw, labels)
        return {"method": "isotonic", "fitted_on": int(len(labels)), "x_thresholds": model.X_thresholds_.tolist(), "y_thresholds": model.y_thresholds_.tolist()}
    model = LogisticRegression(C=10.0, max_iter=1000, random_state=SEED).fit(raw.reshape(-1, 1), labels)
    return {"method": "platt", "fitted_on": int(len(labels)), "regularization_C": 10.0, "coef": float(model.coef_[0][0]), "intercept": float(model.intercept_[0])}


def apply_calibrator(raw: np.ndarray, calibration: dict[str, Any]) -> np.ndarray:
    if calibration["method"] == "raw":
        return np.clip(raw, 0.0, 1.0)
    if calibration["method"] == "isotonic":
        return np.interp(raw, calibration["x_thresholds"], calibration["y_thresholds"])
    logit = np.clip(float(calibration["coef"]) * raw + float(calibration["intercept"]), -60, 60)
    return 1.0 / (1.0 + np.exp(-logit))


def feature_distributions(table: pd.DataFrame, feature_names: tuple[str, ...] = MODEL_FEATURES) -> dict[str, dict[str, float | None]]:
    result: dict[str, dict[str, float | None]] = {}
    for name in feature_names:
        values = pd.to_numeric(table[name], errors="coerce").dropna().to_numpy(dtype="float64")
        result[name] = {
            "p01": None if not len(values) else float(np.quantile(values, 0.01)),
            "p99": None if not len(values) else float(np.quantile(values, 0.99)),
            "median": None if not len(values) else float(np.median(values)),
        }
    return result


def select_threshold(labels: np.ndarray, probabilities: np.ndarray, target_precision: float) -> dict[str, Any]:
    if len(np.unique(labels)) < 2:
        return {"target_precision": target_precision, "threshold": None, "reachable": False, "reason": "validation has one class"}
    precision, recall, thresholds = precision_recall_curve(labels, probabilities)
    candidates = []
    for p, r, threshold in zip(precision[:-1], recall[:-1], thresholds, strict=False):
        if float(p) >= target_precision:
            candidates.append((float(threshold), float(p), float(r)))
    if not candidates:
        return {"target_precision": target_precision, "threshold": None, "reachable": False, "reason": "insufficient evidence for requested precision"}
    threshold, val_precision, val_recall = min(candidates, key=lambda row: row[0])
    return {"target_precision": target_precision, "threshold": threshold, "val_precision": val_precision, "val_recall": val_recall, "reachable": True}


def model_params(labels: np.ndarray, profile: str) -> dict[str, Any]:
    """Return deterministic model parameters for a feature profile."""
    positive_weight = max(1.0, float((labels == 0).sum()) / max(1, int(labels.sum())))
    if profile == "transferable":
        return {
            "n_estimators": 200,
            "learning_rate": 0.03,
            "num_leaves": 15,
            "max_depth": 3,
            "min_child_samples": 20,
            "subsample": 0.90,
            "subsample_freq": 1,
            "colsample_bytree": 0.90,
            "scale_pos_weight": positive_weight,
            "n_jobs": 1,
            "random_state": SEED,
            "verbosity": -1,
        }
    return {
        "n_estimators": 300,
        "learning_rate": 0.04,
        "num_leaves": 31,
        "max_depth": 7,
        "min_child_samples": 30,
        "subsample": 0.85,
        "subsample_freq": 1,
        "colsample_bytree": 0.80,
        "scale_pos_weight": positive_weight,
        "n_jobs": 1,
        "random_state": SEED,
        "verbosity": -1,
    }


def train(
    table: pd.DataFrame,
    *,
    target_precision: float = DEFAULT_TARGET_PRECISION,
    allow_unknown_absence: bool = False,
    feature_profile: str = "transferable",
    calibration_method: str = "auto",
    train_end_year: int | None = None,
    calibration_year: int | None = None,
) -> tuple[lgb.LGBMClassifier, dict[str, Any], dict[str, Any]]:
    table = table.copy()
    for name in MODEL_FEATURES:
        table[name] = pd.to_numeric(table[name], errors="coerce")
    excluded_unknown_absence = 0
    if not allow_unknown_absence:
        labels = pd.to_numeric(table["label"], errors="raise").astype(int)
        if "negative_eligible" in table:
            eligible = table["negative_eligible"].fillna(False).astype(bool)
        elif "label_confidence" in table:
            eligible = table["label_confidence"].astype(str).ne("unknown_absence")
        else:
            raise ValueError(
                "safe avalanche training requires negative_eligible or label_confidence; "
                "use --allow-unknown-absence only for exploratory training"
            )
        keep = (labels == 1) | eligible
        excluded_unknown_absence = int((~keep).sum())
        table = table.loc[keep].copy()
    validate_feature_names(list(MODEL_FEATURES))
    model_features = features_for_profile(feature_profile)
    validate_table(table)
    if (train_end_year is None) != (calibration_year is None):
        raise ValueError("train_end_year and calibration_year must be provided together")
    if train_end_year is not None and calibration_year is not None:
        if train_end_year >= calibration_year:
            raise ValueError("train_end_year must be earlier than calibration_year")
        timestamps = pd.to_datetime(table["reference_timestamp"], utc=True)
        train_mask = timestamps.dt.year <= train_end_year
        validation_mask = timestamps.dt.year == calibration_year
        fit_mask = timestamps.dt.year <= calibration_year
        if not train_mask.any() or not validation_mask.any() or not fit_mask.any():
            raise ValueError("explicit temporal split produced an empty partition")
        if train_mask.sum() < 2 or validation_mask.sum() < 2:
            raise ValueError("explicit temporal split must have distinct train and calibration rows")
        if table.loc[train_mask, "label"].nunique() < 2 or table.loc[validation_mask, "label"].nunique() < 2:
            raise ValueError("explicit temporal partitions must contain both classes")
        train_table, validation_table, fit_table = table.loc[train_mask], table.loc[validation_mask], table.loc[fit_mask]
        split = {
            "strategy": "explicit-temporal-calibration",
            "train_end_year": train_end_year,
            "calibration_year": calibration_year,
            "fit_years": sorted(pd.to_datetime(fit_table["reference_timestamp"], utc=True).dt.year.unique().tolist()),
            "held_out_years": sorted(pd.to_datetime(table.loc[~fit_mask, "reference_timestamp"], utc=True).dt.year.unique().tolist()),
        }
    else:
        is_validation, split = split_spatiotemporal(table)
        train_table, validation_table, fit_table = table.loc[~is_validation], table.loc[is_validation], table
    y_train = train_table["label"].to_numpy(dtype="int8")
    y_validation = validation_table["label"].to_numpy(dtype="int8")
    params = model_params(y_train, feature_profile)
    holdout = lgb.LGBMClassifier(**params).fit(train_table[list(model_features)], y_train)
    raw_validation = holdout.predict_proba(validation_table[list(model_features)])[:, 1]
    calibration = fit_calibrator(raw_validation, y_validation, calibration_method)
    calibrated = apply_calibrator(raw_validation, calibration)
    selection = select_threshold(y_validation, calibrated, target_precision)
    threshold = selection.get("threshold")
    metadata: dict[str, Any] = {
        "model_version": "avalanche-lgbm-v2-transferable" if feature_profile == "transferable" else "avalanche-lgbm-v1-full",
        "prediction_target": f"avalanche occurrence in a 1 km cell during next {PREDICTION_HORIZON_HOURS} hours",
        "feature_names": list(model_features),
        "feature_contract": list(MODEL_FEATURES),
        "feature_profile": feature_profile,
        "feature_groups": feature_groups(),
        "split": split,
        "train": metrics(y_train, holdout.predict_proba(train_table[list(model_features)])[:, 1]),
        "validation": metrics(y_validation, calibrated, threshold),
        "prevalence_pr_baseline": float(y_validation.mean()),
        "threshold_selection": selection,
        "calibration": calibration,
        "hyperparameters": params,
        "training_date": datetime.now(UTC).isoformat(timespec="seconds"),
        "training_years": sorted(pd.to_datetime(fit_table["reference_timestamp"], utc=True).dt.year.unique().tolist()),
        "held_out_years": sorted(pd.to_datetime(table.loc[~table.index.isin(fit_table.index), "reference_timestamp"], utc=True).dt.year.unique().tolist()),
        "label_quality": fit_table.get("label_confidence", pd.Series(dtype=str)).value_counts().to_dict(),
        "feature_distributions": feature_distributions(fit_table, model_features),
        "feature_missing_rates": {name: round(float(fit_table[name].isna().mean()), 6) for name in model_features},
        "ood_threshold": DEFAULT_OOD_THRESHOLD,
        "abstention_band": DEFAULT_ABSTENTION_BAND,
        "selected_threshold": threshold,
        "negative_label_policy": {
            "allow_unknown_absence": allow_unknown_absence,
            "min_coverage_for_observed_no_event": DEFAULT_MIN_NEGATIVE_COVERAGE,
            "excluded_unknown_absence_count": excluded_unknown_absence,
        },
        "limitations": [
            "avalanche occurrence catalogs are incomplete and are not proof of no avalanche",
            "calibrated probabilities are valid only within the represented climate, terrain, and reporting domain",
            "persistent weak-layer and field observation variables remain optional until a source supplies them",
        ],
    }
    final = lgb.LGBMClassifier(**params).fit(fit_table[list(model_features)], fit_table["label"].to_numpy(dtype="int8"))
    return final, metadata, calibration


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", type=Path, default=DEFAULT_TABLE)
    parser.add_argument("--artifacts", type=Path, default=DEFAULT_ARTIFACTS)
    parser.add_argument("--target-precision", type=float, default=float(os.environ.get("AVALANCHE_TARGET_PRECISION", DEFAULT_TARGET_PRECISION)))
    parser.add_argument("--feature-profile", choices=("transferable", "full"), default="transferable")
    parser.add_argument("--calibration-method", choices=("auto", "isotonic", "platt", "raw"), default="auto")
    parser.add_argument("--train-end-year", type=int, help="Explicit pre-calibration training cutoff year.")
    parser.add_argument("--calibration-year", type=int, help="Explicit year used only for calibration and threshold selection.")
    parser.add_argument(
        "--allow-unknown-absence",
        action="store_true",
        help="Exploratory only: train on catalog absences without verified observation coverage.",
    )
    args = parser.parse_args()
    model, metadata, calibration = train(
        read_table(args.table),
        target_precision=args.target_precision,
        allow_unknown_absence=args.allow_unknown_absence,
        feature_profile=args.feature_profile,
        calibration_method=args.calibration_method,
        train_end_year=args.train_end_year,
        calibration_year=args.calibration_year,
    )
    args.artifacts.mkdir(parents=True, exist_ok=True)
    model_path = args.artifacts / MODEL_FILENAME
    partial = model_path.with_name(model_path.name + ".part")
    model.booster_.save_model(str(partial))
    partial.replace(model_path)
    (args.artifacts / METADATA_FILENAME).write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    (args.artifacts / CALIBRATION_FILENAME).write_text(json.dumps(calibration, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"model": str(model_path), "validation": metadata["validation"], "threshold": metadata["selected_threshold"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
