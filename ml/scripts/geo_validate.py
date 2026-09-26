#!/usr/bin/env python3
"""Leave-one-region-out (LORO) geographic validation of the regional susceptibility model.

Run from the repo root:
  python ml/scripts/geo_validate.py [--table PATH] [--out DIR] [--families a,b] [--skip-spatial-cv]
                                    [--skip-ablation] [--skip-diagnostics] [--bootstrap N]

Reads `data/processed/regional_labels.parquet` (build_regional_features.py) and writes CSV and JSON
tables to `ml/artifacts/geo_validation/`.

Design, with nothing chosen on the rows being scored:
  - The training area is cut into six named regions (lowland west / Cascades east of
    REGION_LON_SPLIT, times south / central / north at REGION_LAT_SPLITS).
  - Outer loop: each region is held out in turn. Training rows within CV_BUFFER_M of any held-out
    row are dropped, so no 30 m feature window (widest 1 km) straddles the two sets.
  - Inner loop, on the outer training rows only: leave one of the remaining regions out at a time
    (same buffer). Its out-of-fold scores pick the family's hyperparameters (log loss), fit the
    Platt and isotonic calibrators, and pick every threshold. The outer region is then scored once.
  - Rainier (the `external` rows) is never in any loop. The final fit uses all six regions, with
    calibrators and thresholds from their LORO out-of-fold scores, and scores Rainier once.
  - The recommended family is chosen from mean LORO metrics by the rule in `select_family`, before
    the Rainier numbers are computed.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.spatial import cKDTree
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent))
import geo_metrics as gm  # noqa: E402
import train_regional_susceptibility as trs  # noqa: E402
from build_regional_features import GRID_CRS, TABLE_PATH  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "ml" / "artifacts" / "geo_validation"

# Regions: lowland west of REGION_LON_SPLIT (Puget lowland margin and foothills) and Cascades east
# of it, each cut into south / central / north at REGION_LAT_SPLITS. The cuts sit on the same
# 0.35 x 0.275 degree lattice used to count positives, so every region holds 50+ positives.
REGION_LON_SPLIT = -121.9
REGION_LAT_SPLITS = (46.95, 47.225)
REGIONS = ("south_lowland", "south_cascades", "central_lowland", "central_cascades",
           "north_lowland", "north_cascades")
EXTERNAL_REGION = "rainier"
CV_BUFFER_M = trs.CV_BUFFER_M
RANDOM_SEED = trs.RANDOM_SEED
PRODUCTION_THRESHOLD = trs.HIGH_THRESHOLD  # shared bins: "high" starts at 0.45 on the calibrated map
BOOTSTRAP_REPS = 1000

MODEL_FEATURES = tuple(trs.MODEL_FEATURES)
CATEGORICAL = trs.CATEGORICAL
LANDCOVER_CLASSES = trs.LANDCOVER_CLASSES

# Pre-registered selection rule, applied to mean LORO metrics only: the simplest family whose mean
# PR-AUC and mean ROC-AUC are each within SELECTION_TOLERANCE of the best non-random family.
SELECTION_TOLERANCE = 0.01


@dataclass(frozen=True)
class Family:
    name: str
    kind: str  # "random", "logistic" or "lgbm"
    features: tuple[str, ...]
    grid: tuple[dict, ...]
    complexity: int  # order used by the selection rule, simplest first
    note: str = ""


FAMILIES = (
    Family("random", "random", (), ({},), 0, "uniform random scores: ROC-AUC 0.5, PR-AUC = prevalence"),
    Family("slope_only", "logistic", ("slope",), ({"C": 1.0},), 1, "logistic on slope alone"),
    Family("logistic", "logistic", MODEL_FEATURES,
           ({"C": 0.01}, {"C": 0.1}, {"C": 1.0}), 2, "L2 logistic, standardized, one-hot land cover"),
    Family("logistic_balanced", "logistic", MODEL_FEATURES,
           tuple({"C": c, "class_weight": "balanced"} for c in (0.01, 0.1, 1.0)), 3,
           "same with balanced class weights"),
    Family("lgbm_stumps", "lgbm", MODEL_FEATURES,
           ({"num_leaves": 2, "min_child_samples": 200}, {"num_leaves": 4, "min_child_samples": 200}), 4,
           "shallow boosting: stumps (additive) or 4-leaf trees"),
    Family("lgbm_current", "lgbm", MODEL_FEATURES, trs.PARAM_GRID, 5, "the deployed family and grid"),
    Family("lgbm_balanced", "lgbm", MODEL_FEATURES,
           ({"num_leaves": 7, "min_child_samples": 200, "scale_pos_weight": 3.0},), 6,
           "deployed params with positives up-weighted 3x"),
)
FAMILY_BY_NAME = {f.name: f for f in FAMILIES}


# --- regions and splits ------------------------------------------------------------------------

def region_of(lon, lat) -> np.ndarray:
    lon, lat = np.asarray(lon, dtype=float), np.asarray(lat, dtype=float)
    band = np.searchsorted(np.asarray(REGION_LAT_SPLITS), lat, side="right")
    east = (lon >= REGION_LON_SPLIT).astype(int)
    names = np.array([["south_lowland", "south_cascades"], ["central_lowland", "central_cascades"],
                      ["north_lowland", "north_cascades"]])
    return names[band, east]


def with_regions(table: pd.DataFrame) -> pd.DataFrame:
    """Add lon, lat and region. External (Rainier) rows get EXTERNAL_REGION."""
    out = table.copy()
    lon, lat = Transformer.from_crs(GRID_CRS, "EPSG:4326", always_xy=True).transform(
        out["x"].to_numpy(), out["y"].to_numpy())
    out["lon"], out["lat"] = lon, lat
    out["region"] = region_of(lon, lat)
    out.loc[out["set"] == "external", "region"] = EXTERNAL_REGION
    return out


def buffered_split(xy: np.ndarray, regions: np.ndarray, held_out: str,
                   buffer_m: float = CV_BUFFER_M) -> tuple[np.ndarray, np.ndarray]:
    """Train mask (other regions, farther than buffer_m from every held-out row) and test mask."""
    test = regions == held_out
    train = ~test
    if test.any() and train.any():
        dist, _ = cKDTree(xy[test]).query(xy[train], k=1, distance_upper_bound=buffer_m)
        train[train] = dist > buffer_m
    return train, test


def min_distance(xy_a: np.ndarray, xy_b: np.ndarray) -> float:
    if len(xy_a) == 0 or len(xy_b) == 0:
        return float("inf")
    return float(cKDTree(xy_b).query(xy_a, k=1)[0].min())


def xy_of(frame: pd.DataFrame) -> np.ndarray:
    return frame[["x", "y"]].to_numpy(dtype=float)


# --- model families ----------------------------------------------------------------------------

class Scorer:
    """A fitted family member. score() returns a 0-1 raw score (not yet calibrated)."""

    def __init__(self, family: Family, params: dict, frame: pd.DataFrame):
        self.family, self.params = family, params
        if family.kind == "random":
            self.model = None
        elif family.kind == "logistic":
            self.model = logistic_pipeline(family.features, params).fit(
                logistic_frame(frame, family.features), frame["label"].to_numpy())
        elif family.kind == "lgbm":
            self.model = trs.fit_model(frame, list(family.features), params)
        else:
            raise ValueError(f"unknown family kind {family.kind!r}")

    def score(self, frame: pd.DataFrame) -> np.ndarray:
        if self.family.kind == "random":
            return coordinate_uniform(frame["x"].to_numpy(), frame["y"].to_numpy())
        if self.family.kind == "logistic":
            return self.model.predict_proba(logistic_frame(frame, self.family.features))[:, 1]
        return trs.raw_score(self.model, frame, list(self.family.features))


def coordinate_uniform(x: np.ndarray, y: np.ndarray, seed: int = RANDOM_SEED) -> np.ndarray:
    """Uniform 0-1 score hashed from the cell coordinates (splitmix64): the same row always gets
    the same score, whatever split it lands in."""
    with np.errstate(over="ignore"):
        z = (np.round(x).astype(np.uint64) * np.uint64(0x9E3779B97F4A7C15)
             ^ np.round(y).astype(np.uint64) ^ np.uint64(seed))
        z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        z = z ^ (z >> np.uint64(31))
    return (z >> np.uint64(11)).astype(np.float64) / float(1 << 53)


def logistic_frame(frame: pd.DataFrame, features) -> pd.DataFrame:
    out = frame[list(features)].copy()
    if CATEGORICAL in out:
        out[CATEGORICAL] = out[CATEGORICAL].fillna(0).astype(int)
    return out


def logistic_pipeline(features, params: dict) -> Pipeline:
    numeric = [f for f in features if f != CATEGORICAL]
    steps = [("num", StandardScaler(), numeric)]
    if CATEGORICAL in features:
        steps.append(("cat", OneHotEncoder(categories=[LANDCOVER_CLASSES], handle_unknown="ignore"), [CATEGORICAL]))
    return Pipeline([
        ("prep", ColumnTransformer(steps)),
        ("lr", LogisticRegression(C=params.get("C", 1.0), class_weight=params.get("class_weight"),
                                  max_iter=5000, random_state=RANDOM_SEED)),
    ])


@dataclass
class Fitted:
    family: Family
    params: dict
    scorer: Scorer
    calibrators: dict[str, gm.Calibrator]
    thresholds: dict[str, dict]
    validation_index: np.ndarray  # table index of rows whose OOF scores fit calibrators and thresholds
    validation_labels: np.ndarray
    validation_scores: np.ndarray
    selection: dict = field(default_factory=dict)


def loro_oof(frame: pd.DataFrame, family: Family, params: dict, buffer_m: float = CV_BUFFER_M) -> np.ndarray:
    """Out-of-fold raw scores: each region of frame scored by a fit on the others (buffered)."""
    xy, regions = xy_of(frame), frame["region"].to_numpy()
    oof = np.full(len(frame), np.nan)
    for region in sorted(set(regions)):
        train, test = buffered_split(xy, regions, region, buffer_m)
        if not train.any() or not frame["label"].to_numpy()[train].any():
            continue
        oof[test] = Scorer(family, params, frame[train]).score(frame[test])
    return oof


def fit_with_validation(frame: pd.DataFrame, family: Family, log=print) -> Fitted:
    """Inner LORO on frame only: pick params, fit calibrators and thresholds, then refit on frame."""
    labels = frame["label"].to_numpy()
    results = []
    for params in family.grid:
        oof = loro_oof(frame, family, params)
        ok = ~np.isnan(oof)
        loss = (log_loss(labels[ok], np.clip(oof[ok], gm.PROB_CLIP, 1 - gm.PROB_CLIP))
                if family.kind != "random" else float("nan"))
        results.append((loss, params, oof))
    if family.kind == "random" or len(results) == 1:
        loss, params, oof = results[0]
    else:
        loss, params, oof = min(results, key=lambda r: r[0])
    ok = ~np.isnan(oof)
    val_index, val_labels, val_scores = frame.index.to_numpy()[ok], labels[ok], oof[ok]
    calibrators = {m: gm.Calibrator(m).fit(val_scores, val_labels) for m in gm.Calibrator.METHODS}
    thresholds = gm.select_thresholds(val_labels, val_scores)
    selection = {"params": params, "inner_log_loss": {json.dumps(r[1], sort_keys=True): r[0] for r in results},
                 "validation_rows": int(ok.sum()), "validation_positives": int(val_labels.sum())}
    if len(results) > 1:
        log(f"      {family.name}: inner LORO picked {params} (log loss {loss:.4f})")
    return Fitted(family, params, Scorer(family, params, frame), calibrators, thresholds,
                  val_index, val_labels, val_scores, selection)


# --- evaluation of one held-out set ------------------------------------------------------------

def evaluate_holdout(fitted: Fitted, test: pd.DataFrame, region: str) -> dict:
    """Score test once; every threshold and calibrator came from fitted's validation rows."""
    overlap = np.intersect1d(fitted.validation_index, test.index.to_numpy())
    if overlap.size:
        raise AssertionError(f"{overlap.size} held-out rows were used to fit calibrators or thresholds")
    labels = test["label"].to_numpy()
    raw = fitted.scorer.score(test)
    probs = {m: c.predict(raw) for m, c in fitted.calibrators.items()}
    ranking = gm.ranking_metrics(labels, raw)
    calibration = []
    for method, p in probs.items():
        row = {"method": method, **gm.probability_metrics(labels, p), **gm.ranking_metrics(labels, p)}
        row["roc_auc_change_vs_raw"] = row["roc_auc"] - ranking["roc_auc"]
        calibration.append(row)
    thresholds = gm.apply_thresholds(labels, raw, fitted.thresholds)
    production = gm.confusion(labels, probs["isotonic"], PRODUCTION_THRESHOLD)
    return {
        "region": region, "family": fitted.family.name, "params": fitted.params,
        "ranking": ranking, "calibration": calibration, "thresholds": thresholds,
        "production_bin_high": production,
        "reliability": {m: gm.reliability_rows(labels, p) for m, p in probs.items()},
        "validation": fitted.selection,
        "_raw": raw, "_probs": probs,
    }


def headline_row(result: dict) -> dict:
    """One flat row per (family, region) for the per-region CSV."""
    rank, cal = result["ranking"], {c["method"]: c for c in result["calibration"]}
    maxf1 = next(t for t in result["thresholds"] if t["policy"] == "max_f1")
    prod = result["production_bin_high"]
    return {
        "family": result["family"], "region": result["region"], "n": rank["n"],
        "positives": rank["positives"], "prevalence": rank["prevalence"], "roc_auc": rank["roc_auc"],
        "pr_auc": rank["pr_auc"], "lift": rank["lift"],
        "brier_raw": cal["raw"]["brier"], "ece_raw": cal["raw"]["ece"],
        "brier_isotonic": cal["isotonic"]["brier"], "ece_isotonic": cal["isotonic"]["ece"],
        "brier_platt": cal["platt"]["brier"], "ece_platt": cal["platt"]["ece"],
        "maxf1_threshold": maxf1.get("threshold"), "precision": maxf1.get("precision"),
        "recall": maxf1.get("recall"), "f1": maxf1.get("f1"), "tp": maxf1.get("tp"), "fp": maxf1.get("fp"),
        "tn": maxf1.get("tn"), "fn": maxf1.get("fn"),
        "bin_high_precision": prod["precision"], "bin_high_recall": prod["recall"], "bin_high_f1": prod["f1"],
        "params": json.dumps(result["params"], sort_keys=True),
    }


SUMMARY_METRICS = ("prevalence", "roc_auc", "pr_auc", "lift", "precision", "recall", "f1",
                   "ece_isotonic", "brier_isotonic", "ece_raw", "bin_high_precision", "bin_high_recall")


def summary_rows(rows: list[dict], scheme: str) -> list[dict]:
    frame = pd.DataFrame(rows)
    out = []
    for family, group in frame.groupby("family", sort=False):
        for metric in SUMMARY_METRICS:
            out.append({"scheme": scheme, "family": family, "metric": metric,
                        **gm.summarize(group[metric].to_numpy(dtype=float))})
    return out


# --- the schemes -------------------------------------------------------------------------------

def run_loro(train: pd.DataFrame, family: Family, log=print) -> dict:
    """Outer LORO for one family. Returns per-region results and pooled outer predictions."""
    xy, regions = xy_of(train), train["region"].to_numpy()
    results, pooled = [], pd.DataFrame(index=train.index, columns=["raw", "isotonic", "threshold_max_f1"],
                                       dtype=float)
    for region in REGIONS:
        if not (regions == region).any():
            continue
        tr, te = buffered_split(xy, regions, region)
        fitted = fit_with_validation(train[tr], family, log)
        result = evaluate_holdout(fitted, train[te], region)
        result["n_train"] = int(tr.sum())
        result["min_train_test_distance_m"] = min_distance(xy[tr], xy[te])
        result["_fitted"], result["_train_index"] = fitted, train.index[tr]
        results.append(result)
        pooled.loc[train.index[te], "raw"] = result["_raw"]
        pooled.loc[train.index[te], "isotonic"] = result["_probs"]["isotonic"]
        pooled.loc[train.index[te], "threshold_max_f1"] = fitted.thresholds["max_f1"]["threshold"]
        r = result["ranking"]
        log(f"    {family.name:18s} {region:17s} ROC {r['roc_auc']:.3f} PR {r['pr_auc']:.3f} "
            f"lift {r['lift']:.2f} prev {r['prevalence']:.3f} (train {int(tr.sum())}, "
            f"min gap {result['min_train_test_distance_m']:.0f} m)")
    return {"results": results, "pooled": pooled}


def run_spatial_cv(train: pd.DataFrame, family: Family, log=print) -> dict:
    """The deployed 10 km block CV (same folds and buffer as train_regional_susceptibility)."""
    x, y, labels = train["x"].to_numpy(), train["y"].to_numpy(), train["label"].to_numpy()
    blocks = trs.block_ids(x, y)
    folds = trs.assign_folds(blocks, labels)
    results = []
    for k in range(trs.N_FOLDS):
        tr, te = trs.split_with_buffer(x, y, blocks, folds, k)
        fitted = fit_with_validation(train[tr], family, log)
        result = evaluate_holdout(fitted, train[te], f"fold_{k}")
        result["n_train"] = int(tr.sum())
        results.append(result)
    return {"results": results}


def select_family(summary: list[dict], tolerance: float = SELECTION_TOLERANCE) -> dict:
    """Simplest non-random family within tolerance of the best mean LORO PR-AUC and ROC-AUC."""
    frame = pd.DataFrame([r for r in summary if r["scheme"] == "loro"])
    means = frame.pivot_table(index="family", columns="metric", values="mean")
    means = means.drop(index="random", errors="ignore")
    best_pr, best_roc = means["pr_auc"].max(), means["roc_auc"].max()
    ok = means[(means["pr_auc"] >= best_pr - tolerance) & (means["roc_auc"] >= best_roc - tolerance)]
    order = sorted(ok.index, key=lambda n: FAMILY_BY_NAME[n].complexity)
    chosen = order[0]
    return {"family": chosen, "rule": (f"simplest family with mean LORO PR-AUC >= best - {tolerance} and "
                                       f"mean LORO ROC-AUC >= best - {tolerance}; complexity order "
                                       + " < ".join(f.name for f in FAMILIES if f.kind != "random")),
            "best_mean_pr_auc": float(best_pr), "best_mean_roc_auc": float(best_roc),
            "eligible": order}


def block_bootstrap(labels, scores, x, y, block_m: float = trs.EXTERNAL_BLOCK_M,
                    reps: int = BOOTSTRAP_REPS, seed: int = RANDOM_SEED) -> dict:
    """Percentile 95% intervals for ROC-AUC, PR-AUC and lift from resampling whole blocks."""
    labels, scores = np.asarray(labels), np.asarray(scores)
    unique, inverse = np.unique(trs.block_ids(x, y, block_m), return_inverse=True)
    members = [np.flatnonzero(inverse == i) for i in range(len(unique))]
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(reps):
        pick = np.concatenate([members[i] for i in rng.integers(0, len(unique), len(unique))])
        if gm.both_classes(labels[pick]):
            draws.append(gm.ranking_metrics(labels[pick], scores[pick]))
    out = {"reps_used": len(draws), "blocks": int(len(unique))}
    for key in ("roc_auc", "pr_auc", "lift"):
        values = np.array([d[key] for d in draws])
        out[key] = [float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))] if draws else None
    return out


def paired_bootstrap(labels, scores_a, scores_b, x, y, block_m: float = trs.EXTERNAL_BLOCK_M,
                     reps: int = BOOTSTRAP_REPS, seed: int = RANDOM_SEED) -> dict:
    """Difference a - b in ROC-AUC and PR-AUC on the same resampled blocks, with 95% intervals."""
    labels = np.asarray(labels)
    unique, inverse = np.unique(trs.block_ids(x, y, block_m), return_inverse=True)
    members = [np.flatnonzero(inverse == i) for i in range(len(unique))]
    rng = np.random.default_rng(seed)
    diffs = {"roc_auc": [], "pr_auc": []}
    for _ in range(reps):
        pick = np.concatenate([members[i] for i in rng.integers(0, len(unique), len(unique))])
        if not gm.both_classes(labels[pick]):
            continue
        a, b = gm.ranking_metrics(labels[pick], scores_a[pick]), gm.ranking_metrics(labels[pick], scores_b[pick])
        for key in diffs:
            diffs[key].append(a[key] - b[key])
    full_a, full_b = gm.ranking_metrics(labels, scores_a), gm.ranking_metrics(labels, scores_b)
    out = {"reps_used": len(diffs["roc_auc"])}
    for key, values in diffs.items():
        out[f"{key}_diff"] = full_a[key] - full_b[key]
        out[f"{key}_diff_ci95"] = [float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))]
    return out


def run_external(train: pd.DataFrame, external: pd.DataFrame, family: Family, reps: int, log=print) -> dict:
    """Final fit on all regions (calibrators and thresholds from their LORO OOF), scored on Rainier once."""
    fitted = fit_with_validation(train, family, log)
    result = evaluate_holdout(fitted, external, EXTERNAL_REGION)
    result["n_train"] = int(len(train))
    result["min_train_test_distance_m"] = min_distance(xy_of(train), xy_of(external))
    result["bootstrap_ci95"] = block_bootstrap(external["label"].to_numpy(), result["_raw"],
                                               external["x"].to_numpy(), external["y"].to_numpy(), reps=reps)
    result["_fitted"] = fitted
    return result


# --- output ------------------------------------------------------------------------------------

def clean(obj, places: int = 4):
    """JSON-safe copy: NaN and inf become null, numpy scalars become Python, floats are rounded."""
    if isinstance(obj, dict):
        return {str(k): clean(v, places) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, (list, tuple)):
        return [clean(v, places) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return None if not math.isfinite(obj) else round(float(obj), places)
    if isinstance(obj, np.ndarray):
        return clean(obj.tolist(), places)
    return obj


def write_csv(rows: list[dict], path: Path) -> None:
    frame = pd.DataFrame(rows)
    frame.to_csv(path, index=False, float_format="%.4f")


def threshold_rows(results: list[dict], scheme: str) -> list[dict]:
    rows = []
    for result in results:
        for t in result["thresholds"]:
            rows.append({"scheme": scheme, "family": result["family"], "region": result["region"],
                         "prevalence": result["ranking"]["prevalence"], **t})
    return rows


def calibration_rows(results: list[dict], scheme: str) -> list[dict]:
    rows = []
    for result in results:
        for c in result["calibration"]:
            rows.append({"scheme": scheme, "family": result["family"], "region": result["region"],
                         "fit_rows": result["validation"]["validation_rows"], **c})
    return rows


def reliability_csv_rows(results: list[dict], scheme: str) -> list[dict]:
    rows = []
    for result in results:
        for method, bins in result["reliability"].items():
            for b in bins:
                rows.append({"scheme": scheme, "family": result["family"], "region": result["region"],
                             "method": method, **b})
    return rows


def prevalence_rows(train: pd.DataFrame, external: pd.DataFrame, spatial: dict | None) -> list[dict]:
    """Prevalence of every split the report evaluates."""
    rows = [{"split": "train_all", "n": len(train), "positives": int(train["label"].sum()),
             "prevalence": gm.prevalence(train["label"])}]
    for region in REGIONS:
        part = train[train["region"] == region]
        rows.append({"split": f"loro:{region}", "n": len(part), "positives": int(part["label"].sum()),
                     "prevalence": gm.prevalence(part["label"])})
    if spatial:
        for result in spatial["results"]:
            r = result["ranking"]
            rows.append({"split": f"spatial_cv:{result['region']}", "n": r["n"], "positives": r["positives"],
                         "prevalence": r["prevalence"]})
    rows.append({"split": "external:rainier", "n": len(external), "positives": int(external["label"].sum()),
                 "prevalence": gm.prevalence(external["label"])})
    return rows


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--table", type=Path, default=TABLE_PATH)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--families", default=",".join(f.name for f in FAMILIES))
    parser.add_argument("--skip-spatial-cv", action="store_true")
    parser.add_argument("--skip-ablation", action="store_true")
    parser.add_argument("--skip-diagnostics", action="store_true")
    parser.add_argument("--bootstrap", type=int, default=BOOTSTRAP_REPS)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    started = time.time()
    log = print
    table = with_regions(pd.read_parquet(args.table))
    train = table[table["set"] == "train"]
    external = table[table["set"] == "external"]
    families = [FAMILY_BY_NAME[n] for n in args.families.split(",")]
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    log(f"{len(train)} training rows in {train['region'].nunique()} regions, {len(external)} Rainier rows")

    loro, spatial = {}, {}
    per_region, spatial_rows = [], []
    for family in families:
        log(f"  LORO: {family.name}")
        loro[family.name] = run_loro(train, family, log)
        per_region += [headline_row(r) for r in loro[family.name]["results"]]
        if not args.skip_spatial_cv:
            log(f"  spatial CV: {family.name}")
            spatial[family.name] = run_spatial_cv(train, family, log)
            spatial_rows += [headline_row(r) for r in spatial[family.name]["results"]]
    summary = summary_rows(per_region, "loro") + (summary_rows(spatial_rows, "spatial_cv") if spatial_rows else [])
    selection = select_family(summary)
    log(f"  selected by the LORO rule: {selection['family']}")

    # Rainier is scored only now, after the selection above is fixed.
    external_results = {}
    for family in families:
        external_results[family.name] = run_external(train, external, family, args.bootstrap, log)
        r = external_results[family.name]["ranking"]
        log(f"  Rainier {family.name:18s} ROC {r['roc_auc']:.3f} PR {r['pr_auc']:.3f} lift {r['lift']:.2f}")
    external_rows = [headline_row(r) for r in external_results.values()]
    chosen = external_results.get(selection["family"])
    comparisons = {}
    if chosen is not None:
        for name, result in external_results.items():
            if name != selection["family"]:
                comparisons[f"{selection['family']}_minus_{name}"] = paired_bootstrap(
                    external["label"].to_numpy(), chosen["_raw"], result["_raw"],
                    external["x"].to_numpy(), external["y"].to_numpy(), reps=args.bootstrap)

    all_loro = [r for f in loro.values() for r in f["results"]]
    all_spatial = [r for f in spatial.values() for r in f["results"]]
    all_external = list(external_results.values())
    write_csv(per_region, out / "loro_per_region.csv")
    write_csv(summary, out / "summary.csv")
    if spatial_rows:
        write_csv(spatial_rows, out / "spatial_cv_per_fold.csv")
    write_csv(external_rows, out / "rainier_external.csv")
    write_csv(threshold_rows(all_loro, "loro") + threshold_rows(all_external, "external"), out / "thresholds.csv")
    write_csv(calibration_rows(all_loro, "loro") + calibration_rows(all_spatial, "spatial_cv")
              + calibration_rows(all_external, "external"), out / "calibration.csv")
    write_csv(reliability_csv_rows(all_loro, "loro") + reliability_csv_rows(all_external, "external"),
              out / "reliability.csv")
    first_spatial = next(iter(spatial.values()), None)
    write_csv(prevalence_rows(train, external, first_spatial), out / "prevalence.csv")

    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "table": str(args.table.relative_to(REPO_ROOT)) if args.table.is_relative_to(REPO_ROOT) else str(args.table),
        "seed": RANDOM_SEED, "buffer_m": CV_BUFFER_M,
        "regions": {"lon_split": REGION_LON_SPLIT, "lat_splits": list(REGION_LAT_SPLITS), "names": list(REGIONS)},
        "families": [{"name": f.name, "kind": f.kind, "features": list(f.features), "grid": list(f.grid),
                      "complexity": f.complexity, "note": f.note} for f in families],
        "selection": selection,
        "loro": {name: [{k: v for k, v in r.items() if k not in ("reliability",)} for r in res["results"]]
                 for name, res in loro.items()},
        "loro_summary": [r for r in summary if r["scheme"] == "loro"],
        "spatial_cv_summary": [r for r in summary if r["scheme"] == "spatial_cv"],
        "external_rainier": {name: {k: v for k, v in r.items() if k not in ("reliability",)}
                             for name, r in external_results.items()},
        "external_rainier_paired_differences": comparisons,
        "runtime_s": round(time.time() - started, 1),
    }
    if not args.skip_ablation:
        import geo_ablation  # imports this module, so loaded late

        log("  ablation")
        ablation = geo_ablation.run_ablation(train, external, log)
        write_csv(ablation["per_split"], out / "ablation_per_split.csv")
        write_csv(ablation["summary"], out / "ablation_summary.csv")
        write_csv(ablation["transfer"], out / "ablation_transfer.csv")
        write_csv(ablation["external"], out / "ablation_rainier.csv")
        report["ablation"] = {k: v for k, v in ablation.items() if k != "per_split"}
    if not args.skip_diagnostics:
        import geo_diagnostics

        log(f"  diagnostics: {selection['family']}")
        report["diagnostics"] = geo_diagnostics.run_diagnostics(
            train, external, loro, external_results, selection["family"], out, log)
    report["runtime_s"] = round(time.time() - started, 1)
    (out / "report.json").write_text(json.dumps(clean(report), indent=2) + "\n")
    log(f"wrote {out.relative_to(REPO_ROOT) if out.is_relative_to(REPO_ROOT) else out} in {report['runtime_s']} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
