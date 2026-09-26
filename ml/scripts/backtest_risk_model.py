#!/usr/bin/env python3
"""Replay a timestamped risk table with the persisted model and calibration artifacts.

This command never reconstructs a historical forecast from realized future rain. It accepts a
table already assembled by ``build_risk_samples.py`` and checks its as-of fields before scoring.
The report labels the result as retrospective or operational-realism constrained because provider
revision history is not available from a normalized table alone.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import train_risk_model as training  # noqa: E402
from build_risk_dataset import assert_no_future_leakage  # noqa: E402
from app.ml.risk_contract import MODEL_FEATURES  # noqa: E402

DEFAULT_TABLE = REPO_ROOT / "data" / "processed" / "landslide_risk.parquet"
DEFAULT_ARTIFACTS = REPO_ROOT / "ml" / "artifacts"


def operational_asof_status(table: pd.DataFrame) -> dict[str, object]:
    checks = {}
    reference = pd.to_datetime(table["reference_timestamp"], utc=True)
    for column in ("feature_asof", "observation_asof", "observed_asof", "forecast_initialization"):
        if column not in table:
            continue
        values = pd.to_datetime(table[column], utc=True, errors="coerce")
        checks[column] = bool((values.dropna() <= reference.loc[values.dropna().index]).all())
    return {
        "asof_checks": checks,
        "status": "operational_realism_constrained" if all(checks.values()) else "retrospective_only",
        "limitation": "provider revision history and historical dissemination latency are not encoded in normalized tables",
    }


def run_backtest(table: pd.DataFrame, model: lgb.Booster, calibration: dict, metadata: dict) -> tuple[pd.DataFrame, dict]:
    training.validate_table(table)
    assert_no_future_leakage(table)
    raw = model.predict(table[list(MODEL_FEATURES)])
    probability = training.apply_calibrator(np.asarray(raw, dtype="float64"), calibration)
    threshold = metadata.get("selected_threshold")
    state = np.full(len(table), "UNCERTAIN", dtype=object)
    if threshold is not None:
        state = np.where(probability >= float(threshold), "HIGH_RISK", "NOT_HIGH_RISK")
    predictions = table[["cell_id", "reference_timestamp", "label"]].copy()
    predictions["calibrated_probability"] = probability
    predictions["state"] = state
    groups = table.get("storm_group", table["reference_timestamp"].astype(str).str.slice(0, 10))
    report = {
        "prediction_target": "rainfall-triggered landslide in cell during next 72 hours",
        "rows": len(predictions),
        "state_counts": predictions["state"].value_counts().to_dict(),
        "metrics": training.evaluate(table["label"].to_numpy(dtype="int8"), probability),
        "threshold": training.threshold_metrics(
            table["label"].to_numpy(dtype="int8"),
            probability,
            threshold,
            table["reference_timestamp"],
        ),
        "slices": training.slice_metrics(table, probability),
        "confidence_intervals": training.grouped_bootstrap_intervals(
            table["label"].to_numpy(dtype="int8"), probability, groups,
        ),
        "operational_replay": operational_asof_status(table),
        "model_version": metadata.get("model_version"),
        "calibration_method": calibration.get("method"),
    }
    return predictions, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", type=Path, default=DEFAULT_TABLE)
    parser.add_argument("--artifacts", type=Path, default=DEFAULT_ARTIFACTS)
    parser.add_argument("--report", type=Path, default=DEFAULT_ARTIFACTS / "risk_backtest_report.json")
    parser.add_argument("--predictions", type=Path, default=REPO_ROOT / "data" / "processed" / "risk_backtest_predictions.parquet")
    args = parser.parse_args()
    table = training.read_table(args.table)
    model = lgb.Booster(model_file=str(args.artifacts / training.MODEL_FILENAME))
    metadata = json.loads((args.artifacts / training.METADATA_FILENAME).read_text(encoding="utf-8"))
    calibration = json.loads((args.artifacts / training.CALIBRATION_FILENAME).read_text(encoding="utf-8"))
    predictions, report = run_backtest(table, model, calibration, metadata)
    args.predictions.parent.mkdir(parents=True, exist_ok=True)
    predictions.to_parquet(args.predictions, index=False)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(args.report), "predictions": str(args.predictions), "metrics": report["metrics"], "threshold": report["threshold"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
