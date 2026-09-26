#!/usr/bin/env python3
"""Train the landslide susceptibility model (implementation step 12).

Reads the step 11 outputs and writes, relative to the repo root:
  ml/artifacts/susceptibility.tif          0-1 susceptibility on the 30 m grid (gitignored)
  ml/artifacts/metrics.json                method, AUC, precision at the high threshold
  ml/artifacts/feature_importance.json     what drives the map
  ml/artifacts/susceptibility_lgbm.txt     the LightGBM model, when one is trained

With data/processed/features.parquet (labeled pixels) it trains a LightGBM classifier,
scores it on held-out spatial blocks, then refits on every row to predict the map.
Without labels it falls back to a knowledge-driven index (a weighted combination of the
same seven features) so the map, tiles, and live model can run. metrics.json then says
trained: false and auc: null. Rerun once the landslide points exist.

Run from the repo root:
  python ml/scripts/train_susceptibility.py [--table PATH] [--artifacts DIR]
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import rasterio
from sklearn.metrics import precision_score, roc_auc_score

REPO_ROOT = Path(__file__).resolve().parents[2]
STACK_PATH = REPO_ROOT / "data" / "processed" / "features.tif"
TABLE_PATH = REPO_ROOT / "data" / "processed" / "features.parquet"
ARTIFACTS_DIR = REPO_ROOT / "ml" / "artifacts"

FEATURES = ["elevation", "slope", "aspect", "curvature", "dist_drainage", "landcover", "twi"]

# Shared facts: the lower edge of the "high" bin.
HIGH_THRESHOLD = 0.45
# Hold out whole regions until at least this share of the positives sits in the test set.
TEST_POSITIVE_SHARE = 0.2
RANDOM_SEED = 12

LGBM_PARAMS = {
    "n_estimators": 300,
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_child_samples": 20,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "random_state": RANDOM_SEED,
    "verbose": -1,
}

# Knowledge-driven fallback. A weighted linear combination of factor scores is the standard
# expert method when no landslide inventory exists (Guzzetti et al. 1999, Geomorphology 31).
# Each weight is a judgment for shallow landslides and debris flows on a glaciated volcano.
INDEX_WEIGHTS = {
    "slope": 0.35,          # the main control: shallow failures cluster on 30-45 degree slopes
    "dist_drainage": 0.20,  # debris flows start in and run down steep channels
    "landcover": 0.20,      # bare ground and moraine fail far more often than forest
    "twi": 0.15,            # wetter cells saturate first
    "curvature": 0.10,      # concave hollows gather water and soil
}
# The weighted sum bunches up between about 0.25 and 0.55. Rain is one number for the whole
# box, so every spatial difference in the live heat map comes from this layer: stretch it so
# these percentiles of the box map to 0 and 1. Values are then relative to the Rainier box.
INDEX_STRETCH_PERCENTILES = (2, 98)
# Land cover scores by ESA WorldCover class. Water cannot slide.
LANDCOVER_SCORE = {
    10: 0.3,   # tree cover: roots hold soil
    20: 0.6,   # shrubland
    30: 0.7,   # grassland
    40: 0.4,   # cropland
    50: 0.2,   # built-up
    60: 1.0,   # bare or sparse vegetation: loose moraine and ash
    70: 0.5,   # snow and ice: glacier margins shed debris flows at Rainier
    80: 0.0,   # permanent water
    90: 0.3,   # herbaceous wetland
    95: 0.3,   # mangroves
    100: 0.8,  # moss and lichen: thin cover on steep ground
}


def rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)


def read_stack() -> tuple[np.ndarray, dict]:
    with rasterio.open(STACK_PATH) as ds:
        if list(ds.descriptions) != FEATURES:
            raise SystemExit(f"{rel(STACK_PATH)} bands {ds.descriptions} do not match {FEATURES}")
        return ds.read(), ds.profile


def as_frame(values: dict[str, np.ndarray]) -> pd.DataFrame:
    """Feature frame with land cover as a categorical, as LightGBM expects."""
    frame = pd.DataFrame({name: values[name] for name in FEATURES})
    frame["landcover"] = frame["landcover"].fillna(0).astype("int16").astype("category")
    return frame


def split_regions(table: pd.DataFrame) -> list[int]:
    """Whole regions for the test set, holding at least TEST_POSITIVE_SHARE of the positives."""
    positives = table[table["label"] == 1].groupby("region").size()
    order = np.random.default_rng(RANDOM_SEED).permutation(positives.index.to_numpy())
    test, held = [], 0
    for region in order:
        if held >= TEST_POSITIVE_SHARE * positives.sum() or len(test) == len(order) - 1:
            break
        test.append(int(region))
        held += positives[region]
    return sorted(test)


def train(table: pd.DataFrame) -> tuple[lgb.LGBMClassifier, dict, dict]:
    """Score on held-out regions, then refit on everything for the map."""
    test_regions = split_regions(table)
    is_test = table["region"].isin(test_regions)
    train_rows, test_rows = table[~is_test], table[is_test]
    if test_rows["label"].nunique() < 2 or train_rows["label"].nunique() < 2:
        raise SystemExit("the spatial split left one side with a single class; add labels or regions")

    holdout = lgb.LGBMClassifier(**LGBM_PARAMS).fit(as_frame(train_rows), train_rows["label"])
    scores = holdout.predict_proba(as_frame(test_rows))[:, 1]
    predicted_high = scores >= HIGH_THRESHOLD
    metrics = {
        "method": "lightgbm",
        "trained": True,
        "auc": round(float(roc_auc_score(test_rows["label"], scores)), 4),
        "precision_at_high": round(float(precision_score(test_rows["label"], predicted_high, zero_division=0)), 4),
        "high_threshold": HIGH_THRESHOLD,
        "test_regions": test_regions,
        "train_rows": len(train_rows),
        "test_rows": len(test_rows),
        "positives": int(table["label"].sum()),
        "note": "Scores are on held-out spatial blocks. The map comes from a refit on every row. "
                "Negatives were sampled 1:3, so read the output as relative susceptibility.",
    }

    final = lgb.LGBMClassifier(**LGBM_PARAMS).fit(as_frame(table), table["label"])
    gain = final.booster_.feature_importance(importance_type="gain")
    importance = {name: round(float(g / gain.sum()), 4) for name, g in zip(FEATURES, gain, strict=True)}
    return final, metrics, importance


def predict_map(model: lgb.LGBMClassifier, stack: np.ndarray) -> np.ndarray:
    """Susceptibility for every cell that has the required features."""
    required = [i for i, name in enumerate(FEATURES) if name != "aspect"]
    valid = ~np.isnan(stack[required]).any(axis=0)
    frame = as_frame({name: stack[i][valid] for i, name in enumerate(FEATURES)})
    out = np.full(stack.shape[1:], np.nan, dtype="float32")
    out[valid] = model.predict_proba(frame)[:, 1]
    return out


def ramp(values: np.ndarray, low: float, high: float) -> np.ndarray:
    return np.clip((values - low) / (high - low), 0, 1)


def knowledge_driven_index(stack: np.ndarray) -> np.ndarray:
    """Weighted combination of factor scores, 0-1, NaN outside the data."""
    band = {name: stack[i] for i, name in enumerate(FEATURES)}
    scores = {
        # Rises from 15 to 35 degrees, eases on cliffs steeper than 45 where little soil stays.
        "slope": ramp(band["slope"], 15, 35) * (1 - 0.4 * ramp(band["slope"], 45, 60)),
        "dist_drainage": np.exp(-band["dist_drainage"] / 150),
        "landcover": np.vectorize(lambda c: LANDCOVER_SCORE.get(int(c), 0.4) if not np.isnan(c) else np.nan)(
            band["landcover"]),
        "twi": ramp(band["twi"], 4, 12),
        "curvature": ramp(-band["curvature"], 0, 5),
    }
    index = sum(weight * scores[name] for name, weight in INDEX_WEIGHTS.items())
    index[np.isnan(band["elevation"])] = np.nan
    low, high = np.nanpercentile(index, INDEX_STRETCH_PERCENTILES)
    index = np.clip((index - low) / (high - low), 0, 1)
    index[band["landcover"] == 80] = 0.0
    return index.astype("float32")


def write_raster(path: Path, values: np.ndarray, profile: dict, method: str) -> None:
    profile = {**profile, "count": 1, "dtype": "float32", "nodata": np.nan, "predictor": 3}
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(values, 1)
        dst.set_band_description(1, "susceptibility")
        dst.update_tags(METHOD=method, SOURCE="ml/scripts/train_susceptibility.py")


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the susceptibility model and write the map.")
    parser.add_argument("--table", type=Path, default=TABLE_PATH, help="labeled table from step 11")
    parser.add_argument("--artifacts", type=Path, default=ARTIFACTS_DIR, help="output directory")
    args = parser.parse_args()
    args.artifacts.mkdir(parents=True, exist_ok=True)

    stack, profile = read_stack()
    if args.table.exists():
        table = pd.read_parquet(args.table)
        model, metrics, importance = train(table)
        susceptibility = predict_map(model, stack)
        model.booster_.save_model(str(args.artifacts / "susceptibility_lgbm.txt"))
        print(f"LightGBM on {len(table)} labeled pixels. Held-out regions {metrics['test_regions']}: "
              f"AUC {metrics['auc']}, precision at >= {HIGH_THRESHOLD} {metrics['precision_at_high']}")
    else:
        susceptibility = knowledge_driven_index(stack)
        importance = dict(INDEX_WEIGHTS)
        metrics = {
            "method": "knowledge-driven index",
            "trained": False,
            "auc": None,
            "precision_at_high": None,
            "high_threshold": HIGH_THRESHOLD,
            "weights": INDEX_WEIGHTS,
            "stretch_percentiles": INDEX_STRETCH_PERCENTILES,
            "note": f"No labeled table at {rel(args.table)}: the landslide points are not downloaded yet, "
                    "so no model was trained and no AUC was measured. Rerun steps 10 to 12 once they exist.",
        }
        print(f"No labeled table at {rel(args.table)}. Wrote the knowledge-driven index instead. AUC: not measured.")

    metrics["created_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    valid = susceptibility[~np.isnan(susceptibility)]
    metrics["map"] = {
        "cells": int(valid.size),
        "mean": round(float(valid.mean()), 4),
        "share_at_or_above_high": round(float((valid >= HIGH_THRESHOLD).mean()), 4),
    }
    write_raster(args.artifacts / "susceptibility.tif", susceptibility, profile, metrics["method"])
    (args.artifacts / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    (args.artifacts / "feature_importance.json").write_text(
        json.dumps({"method": metrics["method"], "importance": importance}, indent=2) + "\n")

    print(f"wrote {rel(args.artifacts / 'susceptibility.tif')}: {valid.size} cells, mean {valid.mean():.3f}, "
          f"{(valid >= HIGH_THRESHOLD).mean():.1%} at or above {HIGH_THRESHOLD}")
    print("importance:", ", ".join(f"{k} {v:.2f}" for k, v in sorted(importance.items(), key=lambda kv: -kv[1])))


if __name__ == "__main__":
    main()
