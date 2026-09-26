#!/usr/bin/env python3
"""Train, validate, and publish the regional landslide susceptibility model.

Reads build_regional_features.py outputs and writes, relative to the repo root:
  ml/artifacts/susceptibility.tif               calibrated 0-1 map on the legacy Rainier grid
  ml/artifacts/susceptibility_lgbm.txt          the LightGBM booster (raw scores)
  ml/artifacts/susceptibility_calibration.json  the isotonic map from raw score to probability
  ml/artifacts/feature_importance.json          gain and split importance
  ml/artifacts/metrics.json                     model card: spatial CV and external Rainier metrics
The first run copies the Rainier-only artifacts to ml/artifacts/legacy_rainier_only/.

Validation, in order, with nothing tuned on a test fold:
  1. Spatial block CV: BLOCK_M squares, N_FOLDS folds balanced by positives, and training rows
     within CV_BUFFER_M of any test block dropped.
  2. Inside each outer training set, an inner block CV (same blocks and buffer) picks the
     hyperparameters from PARAM_GRID by out-of-fold log loss and yields out-of-fold scores for
     the isotonic calibrator. The outer test fold is never seen by either.
  3. External test: the model refit on the whole region (Rainier box plus its buffer never in
     training) scores the Rainier box's own labels.
Thresholds are the shared bin edges, fixed in advance.

Run from the repo root:
  python ml/scripts/train_regional_susceptibility.py [--skip-ablation] [--bootstrap N]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.transform import rowcol
from scipy import stats
from shapely.geometry import LineString, shape
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import (
    accuracy_score, average_precision_score, balanced_accuracy_score, brier_score_loss, f1_score, log_loss,
    precision_score, recall_score, roc_auc_score,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_regional_features import GRID_CRS  # noqa: E402
from mountain_packs import RAINIER_BBOX  # noqa: E402
from build_regional_features import (  # noqa: E402
    FEATURES as STACK_FEATURES, MIN_CONFIDENCE, NEGATIVE_EXCLUSION_M, NEGATIVES_PER_POSITIVE,
    RAINIER_HOLDOUT_BUFFER_M, RAINIER_STACK_PATH, TABLE_PATH, WATER_CLASS,
)
from download_region import REGION_BBOX  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS_DIR = REPO_ROOT / "ml" / "artifacts"
LEGACY_DIR = ARTIFACTS_DIR / "legacy_rainier_only"
LEGACY_FILES = ("metrics.json", "susceptibility.tif", "susceptibility_lgbm.txt", "feature_importance.json")
TRAILS_PATH = REPO_ROOT / "data" / "seed" / "trails.geojson"
SEGMENTS_PATH = REPO_ROOT / "data" / "seed" / "trail_segments.geojson"

# Raw elevation is left out of the model. The training positives sit low (lidar mapping covers the
# Puget lowland margin and valley corridors) while the Rainier box runs to 4,392 m, so elevation
# would encode where people mapped and then extrapolate flat across the volcano. Local relief and
# topographic position carry the terrain signal without the absolute height. The ablation run
# trains the same pipeline with elevation and reports it next to the chosen model.
MODEL_FEATURES = [name for name in STACK_FEATURES if name != "elevation"]
CATEGORICAL = "landcover"
LANDCOVER_CLASSES = [10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100]

# Shared facts: bin edges low < 0.2 <= moderate < 0.45 <= high < 0.7 <= extreme.
BIN_EDGES = (0.2, 0.45, 0.7)
HIGH_THRESHOLD = 0.45
EXTREME_THRESHOLD = 0.7
LEVELS = ("low", "moderate", "high", "extreme")

BLOCK_M = 10_000          # CV block side
N_FOLDS = 5
INNER_FOLDS = 4
CV_BUFFER_M = 2_000       # training rows this close to a test block are dropped (twice the widest feature window)
EXTERNAL_BLOCK_M = 2_000  # bootstrap blocks inside the Rainier box
ECE_BINS = 10
BOOTSTRAP_REPS = 1000
RANDOM_SEED = 26

BASE_PARAMS = {
    "objective": "binary", "n_estimators": 400, "learning_rate": 0.05, "subsample": 0.8,
    "subsample_freq": 1, "colsample_bytree": 0.8, "reg_lambda": 1.0, "n_jobs": 1,
    "random_state": RANDOM_SEED, "verbose": -1, "deterministic": True, "force_row_wise": True,
}
# Small, fixed grid searched only by inner CV on training folds.
PARAM_GRID = (
    {"num_leaves": 7, "min_child_samples": 200},
    {"num_leaves": 15, "min_child_samples": 100},
    {"num_leaves": 31, "min_child_samples": 50},
    {"num_leaves": 63, "min_child_samples": 20},
)


def rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)


# --- spatial split -----------------------------------------------------------------------------

def block_ids(x: np.ndarray, y: np.ndarray, block_m: float = BLOCK_M) -> np.ndarray:
    """Integer id of the block_m square each point falls in."""
    bx = np.floor(np.asarray(x) / block_m).astype(np.int64)
    by = np.floor(np.asarray(y) / block_m).astype(np.int64)
    return bx * 1_000_000 + by


def assign_folds(blocks: np.ndarray, labels: np.ndarray, n_folds: int = N_FOLDS,
                 seed: int = RANDOM_SEED) -> np.ndarray:
    """Fold per row. Whole blocks go to one fold; greedy balance on positives, then rows."""
    frame = pd.DataFrame({"block": blocks, "label": labels})
    per_block = frame.groupby("block")["label"].agg(["sum", "size"])
    order = np.random.default_rng(seed).permutation(len(per_block))
    per_block = per_block.iloc[order].sort_values(["sum", "size"], ascending=False, kind="stable")
    positives, rows = np.zeros(n_folds), np.zeros(n_folds)
    fold_of = {}
    for block, (pos, size) in per_block.iterrows():
        fold = int(np.lexsort((rows, positives))[0])
        fold_of[block] = fold
        positives[fold] += pos
        rows[fold] += size
    return frame["block"].map(fold_of).to_numpy()


def distance_to_blocks(x: np.ndarray, y: np.ndarray, test_blocks: set[int], block_m: float = BLOCK_M) -> np.ndarray:
    """Meters from each point to the nearest block square in test_blocks (0 inside one).

    Only the 3 x 3 neighborhood is checked, so this is exact for distances below block_m.
    """
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    bx, by = np.floor(x / block_m).astype(np.int64), np.floor(y / block_m).astype(np.int64)
    best = np.full(x.shape, np.inf)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            nbx, nby = bx + dx, by + dy
            hit = np.isin(nbx * 1_000_000 + nby, np.fromiter(test_blocks, dtype=np.int64))
            if not hit.any():
                continue
            left, bottom = nbx * block_m, nby * block_m
            gx = np.maximum(0, np.maximum(left - x, x - (left + block_m)))
            gy = np.maximum(0, np.maximum(bottom - y, y - (bottom + block_m)))
            best = np.where(hit, np.minimum(best, np.hypot(gx, gy)), best)
    return best


def split_with_buffer(x, y, blocks, folds, test_fold: int, buffer_m: float = CV_BUFFER_M,
                      block_m: float = BLOCK_M) -> tuple[np.ndarray, np.ndarray]:
    """Boolean train and test masks: test is the fold, train is every other row beyond buffer_m of it."""
    test = folds == test_fold
    test_blocks = set(np.unique(blocks[test]).tolist())
    far = distance_to_blocks(x, y, test_blocks, block_m) > buffer_m
    return ~test & far, test


# --- model -------------------------------------------------------------------------------------

def as_frame(table: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    frame = table[features].copy()
    if CATEGORICAL in frame:
        frame[CATEGORICAL] = pd.Categorical(frame[CATEGORICAL].fillna(0).astype(int), categories=LANDCOVER_CLASSES)
    return frame


def fit_model(table: pd.DataFrame, features: list[str], params: dict) -> lgb.LGBMClassifier:
    return lgb.LGBMClassifier(**BASE_PARAMS, **params).fit(as_frame(table, features), table["label"])


def raw_score(model: lgb.LGBMClassifier, table: pd.DataFrame, features: list[str]) -> np.ndarray:
    return model.predict_proba(as_frame(table, features))[:, 1]


def fit_calibrator(scores: np.ndarray, labels: np.ndarray) -> IsotonicRegression:
    return IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip", increasing=True).fit(scores, labels)


def fit_calibrated(table: pd.DataFrame, features: list[str], log=print) -> dict:
    """Inner block CV on table only: pick params by OOF log loss, calibrate on OOF scores, refit."""
    x, y, labels = table["x"].to_numpy(), table["y"].to_numpy(), table["label"].to_numpy()
    blocks = block_ids(x, y)
    folds = assign_folds(blocks, labels, INNER_FOLDS, RANDOM_SEED + 1)
    splits = [split_with_buffer(x, y, blocks, folds, k) for k in range(INNER_FOLDS)]
    results = []
    for params in PARAM_GRID:
        oof = np.full(len(table), np.nan)
        for train_mask, test_mask in splits:
            model = fit_model(table[train_mask], features, params)
            oof[test_mask] = raw_score(model, table[test_mask], features)
        results.append((log_loss(labels, np.clip(oof, 1e-6, 1 - 1e-6)), params, oof))
    loss, params, oof = min(results, key=lambda item: item[0])
    calibrator = fit_calibrator(oof, labels)
    model = fit_model(table, features, params)
    log(f"    inner CV picked {params} (OOF log loss {loss:.4f}; "
        + ", ".join(f"{r[1]['num_leaves']}:{r[0]:.4f}" for r in results) + ")")
    return {"model": model, "calibrator": calibrator, "params": params,
            "inner_log_loss": {str(r[1]["num_leaves"]): round(r[0], 4) for r in results}}


def predict(fitted: dict, table: pd.DataFrame, features: list[str]) -> np.ndarray:
    return fitted["calibrator"].predict(raw_score(fitted["model"], table, features))


# --- metrics -----------------------------------------------------------------------------------

def expected_calibration_error(labels: np.ndarray, probs: np.ndarray, bins: int = ECE_BINS) -> float:
    """Weighted mean |observed rate - mean probability| over equal-width probability bins."""
    labels, probs = np.asarray(labels, dtype=float), np.asarray(probs, dtype=float)
    index = np.minimum((probs * bins).astype(int), bins - 1)
    total = 0.0
    for b in range(bins):
        in_bin = index == b
        if in_bin.any():
            total += in_bin.mean() * abs(labels[in_bin].mean() - probs[in_bin].mean())
    return float(total)


def reliability_table(labels, probs, bins: int = ECE_BINS) -> list[dict]:
    labels, probs = np.asarray(labels, dtype=float), np.asarray(probs, dtype=float)
    index = np.minimum((probs * bins).astype(int), bins - 1)
    rows = []
    for b in range(bins):
        in_bin = index == b
        if in_bin.any():
            rows.append({"bin": [b / bins, (b + 1) / bins], "n": int(in_bin.sum()),
                         "mean_probability": round(float(probs[in_bin].mean()), 4),
                         "observed_rate": round(float(labels[in_bin].mean()), 4)})
    return rows


def threshold_metrics(labels, probs, threshold: float) -> dict:
    predicted = np.asarray(probs) >= threshold
    return {
        "accuracy": float(accuracy_score(labels, predicted)),
        "balanced_accuracy": float(balanced_accuracy_score(labels, predicted)),
        "precision": float(precision_score(labels, predicted, zero_division=0)),
        "recall": float(recall_score(labels, predicted, zero_division=0)),
        "f1": float(f1_score(labels, predicted, zero_division=0)),
        "share_flagged": float(predicted.mean()),
    }


def binary_metrics(labels, probs) -> dict:
    labels, probs = np.asarray(labels), np.asarray(probs)
    out = {
        "n": int(labels.size), "positives": int(labels.sum()), "base_rate": float(labels.mean()),
        "roc_auc": float(roc_auc_score(labels, probs)),
        "pr_auc": float(average_precision_score(labels, probs)),
        "brier": float(brier_score_loss(labels, probs)),
        "ece": expected_calibration_error(labels, probs),
    }
    for name, threshold in (("high", HIGH_THRESHOLD), ("extreme", EXTREME_THRESHOLD)):
        for key, value in threshold_metrics(labels, probs, threshold).items():
            out[f"{key}_at_{name}"] = value
    return out


def flatten_keys(rows: list[dict]) -> list[str]:
    return [k for k in rows[0] if k not in ("n", "positives")]


def fold_summary(rows: list[dict]) -> dict:
    """Mean and 95% t-interval across folds for each metric."""
    out = {}
    k = len(rows)
    t = stats.t.ppf(0.975, k - 1)
    for key in flatten_keys(rows):
        values = np.array([r[key] for r in rows], dtype=float)
        half = t * values.std(ddof=1) / np.sqrt(k)
        out[key] = {"mean": round(float(values.mean()), 4), "ci95": [round(float(values.mean() - half), 4),
                                                                      round(float(values.mean() + half), 4)],
                    "folds": [round(float(v), 4) for v in values]}
    return out


def block_bootstrap(labels, probs, blocks, reps: int | None = None, seed: int = RANDOM_SEED) -> dict:
    """Percentile 95% intervals from resampling whole blocks with replacement."""
    reps = BOOTSTRAP_REPS if reps is None else reps
    labels, probs, blocks = np.asarray(labels), np.asarray(probs), np.asarray(blocks)
    unique, inverse = np.unique(blocks, return_inverse=True)
    members = [np.flatnonzero(inverse == i) for i in range(len(unique))]
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(reps):
        pick = np.concatenate([members[i] for i in rng.integers(0, len(unique), len(unique))])
        if labels[pick].min() == labels[pick].max():
            continue
        draws.append(binary_metrics(labels[pick], probs[pick]))
    out = {"reps_used": len(draws), "blocks": int(len(unique))}
    for key in flatten_keys(draws):
        values = np.array([d[key] for d in draws])
        out[key] = [round(float(np.percentile(values, 2.5)), 4), round(float(np.percentile(values, 97.5)), 4)]
    return out


def rounded(metrics: dict) -> dict:
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in metrics.items()}


# --- validation --------------------------------------------------------------------------------

def spatial_cv(train: pd.DataFrame, features: list[str], log=print) -> dict:
    x, y, labels = train["x"].to_numpy(), train["y"].to_numpy(), train["label"].to_numpy()
    blocks = block_ids(x, y)
    folds = assign_folds(blocks, labels)
    oof = np.full(len(train), np.nan)
    fold_rows, diagnostics = [], []
    for k in range(N_FOLDS):
        train_mask, test_mask = split_with_buffer(x, y, blocks, folds, k)
        log(f"  fold {k}: {int(test_mask.sum())} test rows ({int(labels[test_mask].sum())} positive) in "
            f"{len(np.unique(blocks[test_mask]))} blocks; {int(train_mask.sum())} train rows after the "
            f"{CV_BUFFER_M} m buffer dropped {int((~test_mask & ~train_mask).sum())}")
        fitted = fit_calibrated(train[train_mask], features, log)
        test = train[test_mask]
        oof[test_mask] = predict(fitted, test, features)
        fold_rows.append(binary_metrics(labels[test_mask], oof[test_mask]))
        steep = test["slope"].to_numpy() >= 15
        diagnostics.append({
            "fold": k, "params": fitted["params"],
            "slope_only_roc_auc": round(float(roc_auc_score(labels[test_mask], test["slope"])), 4),
            "roc_auc_slope_ge_15": round(float(roc_auc_score(labels[test_mask][steep], oof[test_mask][steep])), 4),
            "min_distance_train_to_test_block_m": round(float(distance_to_blocks(
                x[train_mask], y[train_mask], set(np.unique(blocks[test_mask]).tolist())).min()), 1),
        })
        log(f"    fold {k}: ROC-AUC {fold_rows[-1]['roc_auc']:.3f}, PR-AUC {fold_rows[-1]['pr_auc']:.3f}, "
            f"ECE {fold_rows[-1]['ece']:.3f}, precision/recall at 0.45 "
            f"{fold_rows[-1]['precision_at_high']:.3f}/{fold_rows[-1]['recall_at_high']:.3f}")
    pooled = binary_metrics(labels, oof)
    confidence = train["confidence"].to_numpy()
    by_confidence = {}
    for level in sorted(set(confidence[labels == 1].astype(int).tolist())):
        keep = (labels == 0) | (confidence == level)
        by_confidence[str(level)] = round(float(roc_auc_score(labels[keep], oof[keep])), 4)
    return {
        "folds": fold_summary(fold_rows),
        "pooled_out_of_fold": rounded(pooled),
        "pooled_block_bootstrap_ci95": block_bootstrap(labels, oof, blocks),
        "reliability": reliability_table(labels, oof),
        "diagnostics": diagnostics,
        "pooled_roc_auc_by_positive_confidence": by_confidence,
        "pooled_slope_only_roc_auc": round(float(roc_auc_score(labels, train["slope"])), 4),
        "_oof": oof,
    }


def external_test(fitted: dict, external: pd.DataFrame, features: list[str]) -> dict:
    labels = external["label"].to_numpy()
    probs = predict(fitted, external, features)
    blocks = block_ids(external["x"], external["y"], EXTERNAL_BLOCK_M)
    wgs = (labels == 0) | (external["source"].to_numpy() == "WA WGS")
    return {
        "metrics": rounded(binary_metrics(labels, probs)),
        "block_bootstrap_ci95": block_bootstrap(labels, probs, blocks),
        "positives_by_source": external.loc[labels == 1, "source"].value_counts().to_dict(),
        "wa_wgs_positives_only": rounded(binary_metrics(labels[wgs], probs[wgs])),
        "slope_only_roc_auc": round(float(roc_auc_score(labels, external["slope"])), 4),
        "_probs": probs,
    }


# --- map and trails ----------------------------------------------------------------------------

def predict_map(fitted: dict, features: list[str]) -> tuple[np.ndarray, dict]:
    with rasterio.open(RAINIER_STACK_PATH) as src:
        stack = src.read()
        names = list(src.descriptions)
    band = {name: stack[names.index(name)] for name in names}
    valid = ~np.isnan(np.stack([band[n] for n in features])).any(axis=0)
    frame = pd.DataFrame({name: band[name][valid] for name in features})
    out = np.full(valid.shape, np.nan, dtype="float32")
    out[valid] = predict(fitted, frame, features).astype("float32")
    out[valid & (band[CATEGORICAL] == WATER_CLASS)] = 0.0  # never trained on water; water cannot slide
    return out, {"cells": int(valid.sum())}


def bin_shares(values: np.ndarray) -> dict:
    v = values[np.isfinite(values)]
    edges = (-np.inf, *BIN_EDGES, np.inf)
    return {level: round(float(((v >= lo) & (v < hi)).mean()), 4)
            for level, lo, hi in zip(LEVELS, edges[:-1], edges[1:], strict=True)}


def sample_line(values: np.ndarray, transform, coords, step_m: float = 10.0) -> np.ndarray:
    to_utm = Transformer.from_crs("EPSG:4326", GRID_CRS, always_xy=True)
    xs, ys = to_utm.transform([c[0] for c in coords], [c[1] for c in coords])
    line = LineString(zip(xs, ys, strict=True))
    points = [line.interpolate(d) for d in np.arange(0, line.length + step_m, step_m)]
    rows, cols = rowcol(transform, [p.x for p in points], [p.y for p in points])
    rows, cols = np.clip(rows, 0, values.shape[0] - 1), np.clip(cols, 0, values.shape[1] - 1)
    return values[rows, cols]


def trail_report(values: np.ndarray, transform) -> dict:
    report = {}
    trails = json.loads(TRAILS_PATH.read_text(encoding="utf-8"))["features"]
    for name in ("Westside Road", "Wonderland Trail", "Skyline Trail"):
        samples = np.concatenate([sample_line(values, transform, shape(f["geometry"]).coords)
                                  for f in trails if f["properties"]["name"] == name])
        samples = samples[np.isfinite(samples)]
        report[name] = {"samples_10m": int(samples.size), "mean": round(float(samples.mean()), 4),
                        "p90": round(float(np.percentile(samples, 90)), 4), "max": round(float(samples.max()), 4),
                        "share_by_level": bin_shares(samples)}
    segments = json.loads(SEGMENTS_PATH.read_text(encoding="utf-8"))["features"]
    worst = np.array([np.nanmax(sample_line(values, transform, shape(f["geometry"]).coords)) for f in segments])
    report["Skyline Trail segments (hero)"] = {
        "segments": len(segments), "max_of_segment_max": round(float(worst.max()), 4),
        "mean_of_segment_max": round(float(worst.mean()), 4),
        "segments_by_level": {k: int(round(v * len(worst))) for k, v in bin_shares(worst).items()},
        "worst_segment_miles": [segments[int(worst.argmax())]["properties"][k] for k in ("start_mile", "end_mile")],
    }
    return report


# --- publishing --------------------------------------------------------------------------------

def back_up_legacy(artifacts: Path) -> list[str]:
    """Copy the Rainier-only artifacts once. Later runs never overwrite the backup."""
    backup = artifacts / LEGACY_DIR.name
    backup.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in LEGACY_FILES:
        source, target = artifacts / name, backup / name
        if source.exists() and not target.exists():
            shutil.copy2(source, target)
            copied.append(name)
    return copied


def atomic_write_text(path: Path, text: str) -> None:
    partial = path.with_name(path.name + ".part")
    partial.write_text(text, encoding="utf-8")
    partial.replace(path)


def write_map(path: Path, values: np.ndarray, template: Path) -> None:
    with rasterio.open(template) as src:
        profile = dict(src.profile)
    profile.update(count=1, dtype="float32", nodata=np.nan, compress="deflate", predictor=3)
    partial = path.with_name(path.name + ".part")
    with rasterio.open(partial, "w", **profile) as dst:
        dst.write(values, 1)
        dst.set_band_description(1, "susceptibility")
        dst.update_tags(METHOD="lightgbm", SOURCE="ml/scripts/train_regional_susceptibility.py",
                        CALIBRATION="isotonic, case-control 1:3")
    partial.replace(path)


def importance(model: lgb.LGBMClassifier, features: list[str]) -> dict:
    gain = model.booster_.feature_importance(importance_type="gain")
    split = model.booster_.feature_importance(importance_type="split")
    return {
        "gain": {n: round(float(g / gain.sum()), 4) for n, g in sorted(zip(features, gain, strict=True), key=lambda t: -t[1])},
        "split": {n: int(s) for n, s in sorted(zip(features, split, strict=True), key=lambda t: -t[1])},
    }


def run_variant(name: str, train: pd.DataFrame, external: pd.DataFrame, features: list[str], log=print) -> dict:
    log(f"[{name}] spatial CV with {len(features)} features")
    started = time.time()
    cv = spatial_cv(train, features, log)
    log(f"[{name}] refit on the whole region for the external test and map")
    fitted = fit_calibrated(train, features, log)
    ext = external_test(fitted, external, features)
    return {"cv": cv, "fitted": fitted, "external": ext, "seconds": round(time.time() - started, 1)}


def strip_private(d: dict) -> dict:
    return {k: v for k, v in d.items() if not k.startswith("_")}


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and validate the regional susceptibility model.")
    parser.add_argument("--table", type=Path, default=TABLE_PATH, help="labeled table from build_regional_features.py")
    parser.add_argument("--artifacts", type=Path, default=ARTIFACTS_DIR, help="output directory")
    parser.add_argument("--skip-ablation", action="store_true", help="skip the with-elevation diagnostic run")
    parser.add_argument("--bootstrap", type=int, default=BOOTSTRAP_REPS, help="block bootstrap repetitions")
    args = parser.parse_args()
    globals()["BOOTSTRAP_REPS"] = args.bootstrap
    started = time.time()
    table = pd.read_parquet(args.table)
    train = table[table["set"] == "train"].reset_index(drop=True)
    external = table[table["set"] == "external"].reset_index(drop=True)
    print(f"{len(train)} training rows ({int(train['label'].sum())} positive), "
          f"{len(external)} external Rainier rows ({int(external['label'].sum())} positive)")

    chosen = run_variant("chosen, no elevation", train, external, MODEL_FEATURES)
    ablation = None if args.skip_ablation else run_variant(
        "ablation, with elevation", train, external, ["elevation"] + MODEL_FEATURES)

    args.artifacts.mkdir(parents=True, exist_ok=True)
    copied = back_up_legacy(args.artifacts)
    fitted = chosen["fitted"]
    susceptibility, map_info = predict_map(fitted, MODEL_FEATURES)
    template = args.artifacts / LEGACY_DIR.name / "susceptibility.tif"
    write_map(args.artifacts / "susceptibility.tif", susceptibility,
              template if template.exists() else RAINIER_STACK_PATH)
    with rasterio.open(args.artifacts / "susceptibility.tif") as src:
        map_transform = src.transform
        grid = {"crs": str(src.crs), "width": src.width, "height": src.height, "cell_m": 30,
                "transform": list(src.transform)[:6]}
    trails = trail_report(susceptibility, map_transform)

    model_path = args.artifacts / "susceptibility_lgbm.txt"
    fitted["model"].booster_.save_model(str(model_path.with_name(model_path.name + ".part")))
    model_path.with_name(model_path.name + ".part").replace(model_path)
    calibrator = fitted["calibrator"]
    atomic_write_text(args.artifacts / "susceptibility_calibration.json", json.dumps({
        "method": "isotonic", "input": "LightGBM raw probability from susceptibility_lgbm.txt",
        "x_thresholds": [round(float(v), 6) for v in calibrator.X_thresholds_],
        "y_thresholds": [round(float(v), 6) for v in calibrator.y_thresholds_],
        "sampling_ratio": f"1:{NEGATIVES_PER_POSITIVE}",
    }, indent=1) + "\n")
    imp = importance(fitted["model"], MODEL_FEATURES)
    atomic_write_text(args.artifacts / "feature_importance.json",
                      json.dumps({"method": "lightgbm", "importance": imp["gain"], "split": imp["split"]}, indent=2) + "\n")

    cv, ext = chosen["cv"], chosen["external"]
    valid = susceptibility[np.isfinite(susceptibility)]
    folds = cv["folds"]
    metrics = {
        "method": "lightgbm",
        "trained": True,
        "auc": folds["roc_auc"]["mean"],
        "precision_at_high": folds["precision_at_high"]["mean"],
        "high_threshold": HIGH_THRESHOLD,
        "extreme_threshold": EXTREME_THRESHOLD,
        "features": MODEL_FEATURES,
        "feature_stack": rel(RAINIER_STACK_PATH),
        "importance": imp["gain"],
        "note": (
            f"Regional model: trained on {len(train)} pixels from the western Cascades {list(REGION_BBOX)}, "
            f"with the Rainier box plus {RAINIER_HOLDOUT_BUFFER_M} m never in training. 'auc' is the mean "
            f"ROC-AUC over {N_FOLDS} spatial block folds ({BLOCK_M // 1000} km blocks, {CV_BUFFER_M} m buffer). "
            f"Probabilities are isotonic-calibrated at the case-control sampling ratio of 1 positive to "
            f"{NEGATIVES_PER_POSITIVE} negatives (base rate 0.25): they are relative susceptibility, not an "
            f"absolute chance that a given pixel fails. On the Rainier box's own labels (external test, n="
            f"{ext['metrics']['n']}) ROC-AUC is {ext['metrics']['roc_auc']:.3f}."
        ),
        "probability_meaning": (
            f"Calibrated share of labeled pixels that are landslides when positives and negatives are sampled "
            f"1:{NEGATIVES_PER_POSITIVE}. Conditional on that ratio and on the inventory's mapping practice; "
            "not a per-pixel or per-year failure rate."
        ),
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "region": {
            "bbox": list(REGION_BBOX), "rainier_bbox": list(RAINIER_BBOX),
            "rainier_holdout_buffer_m": RAINIER_HOLDOUT_BUFFER_M,
        },
        "labels": {
            "inventory": "USGS Landslide Inventories across the United States v3 (doi:10.5066/P14AJF8I)",
            "training_positives": "WA WGS records, confidence >= 3, marine-shore bluffs and depositional fans excluded, "
                                  "one positive per 90 m block; polygon records are their USGS centroid",
            "min_confidence": MIN_CONFIDENCE,
            "negatives": f"> {NEGATIVE_EXCLUSION_M} m from every inventory record (any confidence), inside the mapped "
                         f"footprint (5 km squares with >= 3 WA WGS records), water excluded, 1:{NEGATIVES_PER_POSITIVE}",
            "train_rows": len(train), "train_positives": int(train["label"].sum()),
            "external_rows": len(external), "external_positives": int(external["label"].sum()),
        },
        "validation": {
            "scheme": f"GroupKFold-style spatial blocks: {BLOCK_M // 1000} km squares, {N_FOLDS} folds balanced by "
                      f"positives, training rows within {CV_BUFFER_M} m of a test block dropped. Hyperparameters "
                      f"({len(PARAM_GRID)}-config grid) and the isotonic calibrator come from an inner "
                      f"{INNER_FOLDS}-fold block CV on each outer training set only.",
            "spatial_cv": strip_private(cv),
            "external_rainier": strip_private(ext),
        },
        "calibration": {
            "method": "isotonic on inner out-of-fold scores (nested)",
            "ece_cv_mean": folds["ece"]["mean"], "ece_cv_ci95": folds["ece"]["ci95"],
            "ece_external": ext["metrics"]["ece"],
        },
        "hyperparameters": {"base": {k: v for k, v in BASE_PARAMS.items() if k not in ("verbose",)},
                            "grid": list(PARAM_GRID), "final": fitted["params"]},
        "map": {
            "cells": int(valid.size), "mean": round(float(valid.mean()), 4),
            "share_at_or_above_high": round(float((valid >= HIGH_THRESHOLD).mean()), 4),
            "share_by_level": bin_shares(valid), **map_info,
        },
        "trails": trails,
        "grid": grid,
    }
    if ablation is not None:
        acv, aext = ablation["cv"], ablation["external"]
        metrics["elevation_ablation"] = {
            "decision": "elevation excluded a priori (mapping-effort and extrapolation risk); reported for audit only",
            "cv_roc_auc": acv["folds"]["roc_auc"], "cv_pr_auc": acv["folds"]["pr_auc"],
            "external_roc_auc": aext["metrics"]["roc_auc"], "external_pr_auc": aext["metrics"]["pr_auc"],
            "external_roc_auc_ci95": aext["block_bootstrap_ci95"]["roc_auc"],
            "elevation_gain_share": importance(ablation["fitted"]["model"], ["elevation"] + MODEL_FEATURES)["gain"]["elevation"],
        }
    metrics["legacy_backup"] = {"dir": rel(args.artifacts / LEGACY_DIR.name), "copied_this_run": copied}
    atomic_write_text(args.artifacts / "metrics.json", json.dumps(metrics, indent=2) + "\n")

    print(f"\nspatial CV ({N_FOLDS} folds, mean [95% CI]):")
    for key in ("roc_auc", "pr_auc", "base_rate", "brier", "ece", "accuracy_at_high", "balanced_accuracy_at_high",
                "precision_at_high", "recall_at_high", "f1_at_high", "precision_at_extreme", "recall_at_extreme"):
        print(f"  {key:<26} {folds[key]['mean']:.3f} {folds[key]['ci95']}")
    e = ext["metrics"]
    print(f"external Rainier (n={e['n']}, {e['positives']} positive): ROC-AUC {e['roc_auc']:.3f} "
          f"{ext['block_bootstrap_ci95']['roc_auc']}, PR-AUC {e['pr_auc']:.3f}, ECE {e['ece']:.3f}, "
          f"precision/recall at 0.45 {e['precision_at_high']:.3f}/{e['recall_at_high']:.3f}")
    print(f"map: {metrics['map']['share_by_level']}")
    print(f"wrote {rel(args.artifacts / 'susceptibility.tif')}, susceptibility_lgbm.txt, susceptibility_calibration.json, "
          f"feature_importance.json, metrics.json in {time.time() - started:.0f} s")


if __name__ == "__main__":
    main()
