#!/usr/bin/env python3
"""Train the landslide susceptibility model (implementation steps 12 and 32).

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

--mountain SLUG scores another pack from ml/scripts/mountain_packs.py, under
ml/artifacts/packs/<slug>/. A pack always takes the knowledge-driven index, even when
a table is passed: the LightGBM labels are Rainier's, and a model moved to another
mountain would be a fake number.

Run from the repo root:
  python ml/scripts/train_susceptibility.py [--mountain SLUG] [--table PATH] [--artifacts DIR]
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import lightgbm as lgb
import mountain_packs as mp
import numpy as np
import pandas as pd
import rasterio
from sklearn.metrics import precision_score, roc_auc_score

REPO_ROOT = Path(__file__).resolve().parents[2]

FEATURES = ["elevation", "slope", "aspect", "curvature", "dist_drainage", "landcover", "twi"]
TABLE_COLUMNS = FEATURES + ["label", "region", "row", "col"]

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
    "n_jobs": 1,
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
# Pack indexes have no fitted calibration. After percentile stretching, reserve the upper
# shared risk bins for the strongest terrain signal instead of painting most of a box High
# or Extreme. This monotone curve preserves every cell's rank and leaves low terrain clear.
PACK_INDEX_GAMMA = 2.4
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


def read_stack(stack_path: Path) -> tuple[np.ndarray, dict]:
    with rasterio.open(stack_path) as ds:
        if list(ds.descriptions) != FEATURES:
            raise SystemExit(f"{rel(stack_path)} bands {ds.descriptions} do not match {FEATURES}")
        return ds.read(), ds.profile


def as_frame(values: dict[str, np.ndarray]) -> pd.DataFrame:
    """Feature frame with land cover as a categorical, as LightGBM expects."""
    frame = pd.DataFrame({name: values[name] for name in FEATURES})
    frame["landcover"] = frame["landcover"].fillna(0).astype("int16").astype("category")
    return frame


def validate_table(table: pd.DataFrame) -> None:
    """Reject malformed training input before LightGBM can produce a misleading artifact."""
    missing = [name for name in TABLE_COLUMNS if name not in table.columns]
    if missing:
        raise SystemExit(f"training table is missing required columns: {missing}")
    required_values = [name for name in TABLE_COLUMNS if name != "aspect"]
    if table[required_values].isna().any().any():
        missing_values = table[required_values].columns[table[required_values].isna().any()].tolist()
        raise SystemExit(f"training table has missing values in: {missing_values}")
    labels = set(table["label"].unique().tolist())
    if not labels <= {0, 1}:
        raise SystemExit(f"training labels must be binary 0/1, got {sorted(labels)}")
    if table[["row", "col"]].duplicated().any():
        raise SystemExit("training table contains duplicate pixel coordinates")
    if table["label"].nunique() < 2:
        raise SystemExit("training table must contain both positive and negative labels")


def split_regions(table: pd.DataFrame) -> list[int]:
    """Whole regions for the test set, holding at least TEST_POSITIVE_SHARE of the positives."""
    positives = table[table["label"] == 1].groupby("region").size()
    if len(positives) < 2:
        raise SystemExit("spatial validation needs positive labels in at least two regions")
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
    validate_table(table)
    test_regions = split_regions(table)
    if not test_regions:
        raise SystemExit("spatial validation could not select a held-out region")
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
        "features": FEATURES,
        "note": "Scores are on held-out spatial blocks. The map comes from a refit on every row. "
                "Negatives were sampled 1:3, so read the output as relative susceptibility.",
    }

    final = lgb.LGBMClassifier(**LGBM_PARAMS).fit(as_frame(table), table["label"])
    gain = final.booster_.feature_importance(importance_type="gain")
    total_gain = gain.sum()
    if total_gain <= 0:
        raise SystemExit("LightGBM produced no feature gain; refusing to publish an unusable model")
    importance = {name: round(float(g / total_gain), 4) for name, g in zip(FEATURES, gain, strict=True)}
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
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        index = np.zeros_like(index, dtype="float32")
    else:
        index = np.clip((index - low) / (high - low), 0, 1)
    index[band["landcover"] == 80] = 0.0
    return index.astype("float32")


def write_raster(path: Path, values: np.ndarray, profile: dict, method: str) -> None:
    profile = {**profile, "count": 1, "dtype": "float32", "nodata": np.nan, "predictor": 3}
    partial = path.with_name(path.name + ".part")
    with rasterio.open(partial, "w", **profile) as dst:
        dst.write(values, 1)
        dst.set_band_description(1, "susceptibility")
        dst.update_tags(METHOD=method, SOURCE="ml/scripts/train_susceptibility.py")
    partial.replace(path)


def label_provenance(landslides_path: Path) -> dict:
    """Record the seed catalogs behind the current training table in the model card."""
    if not landslides_path.is_file():
        return {}
    payload = json.loads(landslides_path.read_text(encoding="utf-8"))
    features = payload.get("features", [])
    accuracies = {"exact", "1km"}
    return {
        "seed_events": len(features),
        "label_catalogs": sorted({feature.get("properties", {}).get("catalog") or "unknown" for feature in features}),
        "usable_seed_events": sum(
            (feature.get("properties", {}).get("location_accuracy") or "").lower() in accuracies
            for feature in features
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the susceptibility model and write the map.")
    parser.add_argument("--mountain", default=mp.RAINIER_SLUG,
                        help=f"pack slug from mountain_packs.py (default: {mp.RAINIER_SLUG})")
    parser.add_argument("--table", type=Path, default=None, help="labeled table from step 11 (Rainier only)")
    parser.add_argument("--artifacts", type=Path, default=None, help="output directory")
    args = parser.parse_args()
    pack, paths = mp.get(args.mountain), mp.paths(args.mountain)
    rainier = pack.slug == mp.RAINIER_SLUG
    table_path = args.table or paths.table
    if args.artifacts is None:
        args.artifacts = paths.artifacts
    args.artifacts.mkdir(parents=True, exist_ok=True)

    stack, profile = read_stack(paths.stack)
    if not rainier and table_path.exists():
        # The LightGBM labels are Rainier's; on another mountain they would be a fake number.
        print(f"ignoring {rel(table_path)}: packs always use the knowledge-driven index")
    if rainier and table_path.exists():
        table = pd.read_parquet(table_path)
        model, metrics, importance = train(table)
        susceptibility = predict_map(model, stack)
        model_path = args.artifacts / "susceptibility_lgbm.txt"
        model.booster_.save_model(str(model_path.with_name(model_path.name + ".part")))
        model_path.with_name(model_path.name + ".part").replace(model_path)
        print(f"LightGBM on {len(table)} labeled pixels. Held-out regions {metrics['test_regions']}: "
              f"AUC {metrics['auc']}, precision at >= {HIGH_THRESHOLD} {metrics['precision_at_high']}")
    else:
        susceptibility = knowledge_driven_index(stack)
        if not rainier:
            susceptibility = np.power(susceptibility, PACK_INDEX_GAMMA).astype("float32")
        importance = dict(INDEX_WEIGHTS)
        metrics = {
            "method": "knowledge-driven index",
            "trained": False,
            "auc": None,
            "precision_at_high": None,
            "high_threshold": HIGH_THRESHOLD,
            "weights": INDEX_WEIGHTS,
            "stretch_percentiles": INDEX_STRETCH_PERCENTILES,
            "index_gamma": PACK_INDEX_GAMMA if not rainier else 1.0,
            "note": (
                f"No labeled table at {rel(table_path)}: the landslide points are not downloaded yet, "
                "so no model was trained and no AUC was measured. Rerun steps 10 to 12 once they exist."
                if rainier else
                f"The {pack.name} pack scores the knowledge-driven index. Only Rainier's landslide "
                "inventory is dense enough to train on, so no model was trained and no AUC exists here."
            ),
        }
        print(f"Wrote the knowledge-driven index for {pack.slug}. AUC: not measured.")

    metrics["created_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    valid = susceptibility[~np.isnan(susceptibility)]
    metrics["map"] = {
        "cells": int(valid.size),
        "mean": round(float(valid.mean()), 4),
        "share_at_or_above_high": round(float((valid >= HIGH_THRESHOLD).mean()), 4),
    }
    write_raster(args.artifacts / "susceptibility.tif", susceptibility, profile, metrics["method"])
    metrics["features"] = FEATURES
    metrics["mountain"] = pack.slug
    if rainier:
        metrics.update(label_provenance(paths.landslides))
    metrics["grid"] = {
        "crs": str(profile["crs"]),
        "width": int(profile["width"]),
        "height": int(profile["height"]),
        "cell_m": 30,
    }
    for filename, payload in (
        ("metrics.json", metrics),
        ("feature_importance.json", {"method": metrics["method"], "importance": importance}),
    ):
        output = args.artifacts / filename
        partial = output.with_name(output.name + ".part")
        partial.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        partial.replace(output)

    print(f"wrote {rel(args.artifacts / 'susceptibility.tif')}: {valid.size} cells, mean {valid.mean():.3f}, "
          f"{(valid >= HIGH_THRESHOLD).mean():.1%} at or above {HIGH_THRESHOLD}")
    print("importance:", ", ".join(f"{k} {v:.2f}" for k, v in sorted(importance.items(), key=lambda kv: -kv[1])))


if __name__ == "__main__":
    main()
