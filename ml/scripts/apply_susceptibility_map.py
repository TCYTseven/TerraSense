#!/usr/bin/env python3
"""Apply the trained regional LightGBM to the Rainier feature stack and publish susceptibility.tif.

The live API and Model B read ml/artifacts/susceptibility.tif, not the booster file directly.
After you replace susceptibility_lgbm.txt or susceptibility_calibration.json, run this script so
the map matches the model. It does not retrain.

Requires:
  ml/artifacts/susceptibility_lgbm.txt
  ml/artifacts/susceptibility_calibration.json
  data/processed/rainier_regional_features.tif  (build_regional_features.py --rainier-stack-only)

Run from the repo root:
  python ml/scripts/apply_susceptibility_map.py [--artifacts DIR] [--stack PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import rasterio

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from build_regional_features import RAINIER_STACK_PATH  # noqa: E402
from train_regional_susceptibility import MODEL_FEATURES, predict_map, write_map  # noqa: E402

ARTIFACTS_DIR = REPO_ROOT / "ml" / "artifacts"
MODEL_PATH = ARTIFACTS_DIR / "susceptibility_lgbm.txt"
CALIBRATION_PATH = ARTIFACTS_DIR / "susceptibility_calibration.json"


def rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)


class _BoosterClassifier:
    """Minimal stand-in for LGBMClassifier.predict_proba used by train_regional_susceptibility."""

    def __init__(self, booster: lgb.Booster) -> None:
        self._booster = booster

    def predict_proba(self, frame: pd.DataFrame) -> np.ndarray:
        scores = self._booster.predict(frame)
        scores = np.clip(np.asarray(scores, dtype="float64"), 0.0, 1.0)
        return np.column_stack([1.0 - scores, scores])


def load_fitted(model_path: Path, calibration_path: Path) -> dict:
    if not model_path.is_file():
        raise SystemExit(f"{rel(model_path)} is missing")
    if not calibration_path.is_file():
        raise SystemExit(f"{rel(calibration_path)} is missing")
    booster = lgb.Booster(model_file=str(model_path))
    model_features = list(booster.feature_name())
    if model_features != MODEL_FEATURES:
        raise SystemExit(
            f"booster expects {model_features}, but the regional pipeline uses {MODEL_FEATURES}"
        )
    cal = json.loads(calibration_path.read_text(encoding="utf-8"))
    if cal.get("method") != "isotonic" or "x_thresholds" not in cal or "y_thresholds" not in cal:
        raise SystemExit(f"{rel(calibration_path)} is not an isotonic calibration file")
    x_thresholds = np.asarray(cal["x_thresholds"], dtype="float64")
    y_thresholds = np.asarray(cal["y_thresholds"], dtype="float64")

    class _Calibrator:
        def predict(self, raw: np.ndarray) -> np.ndarray:
            return np.clip(np.interp(raw, x_thresholds, y_thresholds), 0.0, 1.0)

    return {"model": _BoosterClassifier(booster), "calibrator": _Calibrator()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply susceptibility_lgbm.txt to the Rainier stack.")
    parser.add_argument("--artifacts", type=Path, default=ARTIFACTS_DIR, help="directory with model + calibration")
    parser.add_argument("--stack", type=Path, default=RAINIER_STACK_PATH, help="16-band Rainier feature GeoTIFF")
    args = parser.parse_args()
    if not args.stack.is_file():
        raise SystemExit(
            f"{rel(args.stack)} is missing. From repo root: "
            "python ml/scripts/build_regional_features.py --rainier-stack-only"
        )
    fitted = load_fitted(args.artifacts / "susceptibility_lgbm.txt", args.artifacts / "susceptibility_calibration.json")
    susceptibility, _map_info = predict_map(fitted, MODEL_FEATURES)
    out_path = args.artifacts / "susceptibility.tif"
    write_map(out_path, susceptibility, args.stack)
    valid = susceptibility[np.isfinite(susceptibility)]
    print(
        f"wrote {rel(out_path)} from {rel(args.artifacts / 'susceptibility_lgbm.txt')}: "
        f"{int(valid.size)} cells, mean {float(valid.mean()):.4f}, "
        f"share >= 0.45 {float((valid >= 0.45).mean()):.4f}"
    )


if __name__ == "__main__":
    main()
