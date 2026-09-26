#!/usr/bin/env python3
"""Validate the combined terrain x rain index on dated landslides inside the terrain model's region.

Run from the repo root, after event_rain.py and geo_validate.py:
  python ml/scripts/combined_validate.py [--rebuild-points] [--bootstrap N] [--terrain-family NAME]

Live Model B multiplies odds: index = sigmoid(W1*(logit(s) - TERRAIN_BASE_LOGIT) + W0 + W2*r + W3*m).
Its rain weights were fitted on a case-crossover design, where terrain is constant within each
matched set, so that fit says nothing about how terrain and rain combine. This script builds a
2 x 2 space-time design that can:

  case                   a dated landslide's record location, on its event day
  same_place_other_day   that location on the case-crossover control days (rain varies, terrain fixed)
  other_place_same_day   CONTROL_PLACES stable cells in the same 0.1 degree weather cell, event day
                         (terrain varies, rain identical: rain is per weather cell)
  other_place_other_day  those cells on the control days

Stable cells: valid ground in the WA WGS mapped footprint, farther than NEGATIVE_EXCLUSION_M from
every inventory record of any date, the same rule as the terrain negatives.

Leakage guards: each event's terrain score comes from a model that never trained on the event's
region, nor within CV_BUFFER_M of any point of that region's design. Fitted combinations are
out-of-fold by water-year blocks; training also drops rows whose own date is in a held-out water
year. Rain features at lead 0 read the reanalysis next 72 h (a perfect forecast); the
`_no_forecast` variants use only the past.

Rainier: no dated event falls in the Rainier box, so nothing here is Rainier validation.

Writes `ml/artifacts/geo_validation/combined_validation.json` and `combined_*.csv`. The point
table is cached in `data/processed/events/combined_points.parquet`.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.spatial import cKDTree
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_regional_features as brf  # noqa: E402
import event_validate as ev  # noqa: E402
import geo_metrics as gm  # noqa: E402
import geo_validate as gv  # noqa: E402
from download_region import DOWNLOAD_BBOX, REGION_BBOX  # noqa: E402
from event_catalog import WEATHER_GRID_DEG, snap  # noqa: E402
from mountain_packs import RAINIER_BBOX  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
EVENTS_DIR = REPO_ROOT / "data" / "processed" / "events"
POINTS_PATH = EVENTS_DIR / "combined_points.parquet"
OUT_DIR = gv.OUT_DIR

# Live Model B constants, copied from backend/app/ml/model_b.py (a test keeps them equal).
W0, W1, W2, W3 = -1.32, 1.0, 0.92, 0.76
TERRAIN_BASE_LOGIT = float(np.log(0.25 / 0.75))
SUSCEPTIBILITY_CLIP = 1e-3
HIGH_THRESHOLD = 0.45

LEAD_HOURS = 0
CONTROL_PLACES = 4
CASE_DRAWS = 5  # the case point is one record of the cluster; draws vary which one
PRECISE_SOURCES = {"usgs_v3"}  # GLC locations can be off by up to 5 km
SEED = 20260926
KINDS = ("same_place_other_day", "other_place_same_day", "other_place_other_day")
RAIN_COLUMNS = ["rainfall_exceedance", "past_72h_exceedance", "moisture_index", "next_72h_mm", "past_72h_mm",
                "past_7d_mm"]
DEFAULT_TERRAIN_FAMILY = "lgbm_current"


# --- the live formula --------------------------------------------------------------------------

def logit(p) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), SUSCEPTIBILITY_CLIP, 1 - SUSCEPTIBILITY_CLIP)
    return np.log(p / (1 - p))


def sigmoid(z) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(np.asarray(z, dtype=float), -60, 60)))


def live_index(s, r, m) -> np.ndarray:
    return sigmoid(W1 * (logit(s) - TERRAIN_BASE_LOGIT) + W0 + W2 * np.asarray(r) + W3 * np.asarray(m))


# --- points ------------------------------------------------------------------------------------

def load_design(features_path: Path = EVENTS_DIR / "features.parquet",
                records_path: Path = EVENTS_DIR / "records.parquet") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Lead-0 case-crossover rows and the records of every cluster with a record in REGION_BBOX."""
    rows = pd.read_parquet(features_path)
    rows = rows[rows["lead_hours"] == LEAD_HOURS]
    rows, _ = ev.usable_rows(rows, LEAD_HOURS)
    records = pd.read_parquet(records_path)
    inside = brf.in_bbox(records["lon"].to_numpy(), records["lat"].to_numpy(), REGION_BBOX)
    records = records[inside & records["cluster_id"].isin(rows["cluster_id"])]
    rows = rows[rows["cluster_id"].isin(records["cluster_id"])].reset_index(drop=True)
    return rows, records.reset_index(drop=True)


def pick_case_records(records: pd.DataFrame, draws: int = CASE_DRAWS, seed: int = SEED) -> pd.DataFrame:
    """One record per cluster per draw, from the precise records when the cluster has any."""
    rng = np.random.default_rng(seed)
    picks = []
    for cluster_id, group in records.sort_values("record_id").groupby("cluster_id", sort=True):
        precise = group[group["source"].isin(PRECISE_SOURCES)]
        pool = precise if len(precise) else group
        for draw in range(draws):
            rec = pool.iloc[int(rng.integers(0, len(pool)))]
            picks.append({"cluster_id": cluster_id, "draw": draw, "lon": rec["lon"], "lat": rec["lat"],
                          "precise": bool(len(precise) > 0), "record_source": rec["source"]})
    return pd.DataFrame(picks)


def build_points(rows: pd.DataFrame, records: pd.DataFrame, log=print, seed: int = SEED) -> pd.DataFrame:
    """Terrain features at every case record draw and at CONTROL_PLACES stable cells per cluster."""
    transform, width, height = brf.snapped_grid(DOWNLOAD_BBOX)
    shape = (height, width)
    log(f"    building the regional stack {width} x {height} (about a minute)")
    stack = brf.build_stack(transform, shape)
    valid = ~np.isnan(stack).any(axis=0) & (stack[brf.FEATURES.index("landcover")] != brf.WATER_CLASS)
    inventory = brf.read_inventory()
    irow, icol, iin = brf.to_cells(inventory["lon"], inventory["lat"], transform, shape)
    exclusion = pd.read_parquet(EVENTS_DIR / "exclusion_records.parquet")
    erow, ecol, ein = brf.to_cells(exclusion["lon"], exclusion["lat"], transform, shape)
    dist_any = brf.distance_to(np.r_[irow[iin], erow[ein]], np.r_[icol[iin], ecol[ein]], shape)
    fp = inventory[brf.footprint_mask(inventory)]
    frow, fcol, fin = brf.to_cells(fp["lon"], fp["lat"], transform, shape)
    mapped = brf.footprint(frow[fin], fcol[fin], shape)
    stable = valid & mapped & (dist_any > brf.NEGATIVE_EXCLUSION_M)

    rng = np.random.default_rng(seed + 1)
    clusters = rows.drop_duplicates("cluster_id").set_index("cluster_id")
    points = []
    for _, c in pick_case_records(records).iterrows():
        points.append({"cluster_id": c["cluster_id"], "point": f"case_{c['draw']}", "draw": int(c["draw"]),
                       "lon": c["lon"], "lat": c["lat"], "precise": c["precise"]})
    for cluster_id, info in clusters.iterrows():
        cand_lon, cand_lat = weather_cell_candidates(info["cell_lat"], info["cell_lon"], transform, shape, stable)
        if cand_lon.size == 0:
            continue
        chosen = np.sort(rng.choice(cand_lon.size, size=min(CONTROL_PLACES, cand_lon.size), replace=False))
        for j, i in enumerate(chosen):
            points.append({"cluster_id": cluster_id, "point": f"place_{j}", "draw": -1,
                           "lon": float(cand_lon[i]), "lat": float(cand_lat[i]), "precise": True})
    out = pd.DataFrame(points)
    r, c, inside = brf.to_cells(out["lon"], out["lat"], transform, shape)
    out = out[inside].assign(row=r[inside], col=c[inside]).reset_index(drop=True)
    out["x"] = transform.c + (out["col"] + 0.5) * brf.CELL_M
    out["y"] = transform.f - (out["row"] + 0.5) * brf.CELL_M
    for i, name in enumerate(brf.FEATURES):
        out[name] = stack[i, out["row"], out["col"]]
    out["dist_any_record_m"] = dist_any[out["row"], out["col"]]
    out["valid"] = valid[out["row"], out["col"]]
    return out


def weather_cell_candidates(cell_lat: float, cell_lon: float, transform, shape,
                            stable: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Lon/lat of the stable grid cells whose centers snap to this weather cell, inside REGION_BBOX."""
    half = WEATHER_GRID_DEG / 2
    to_utm = Transformer.from_crs("EPSG:4326", brf.GRID_CRS, always_xy=True)
    xs, ys = to_utm.transform([cell_lon - half, cell_lon + half] * 2, [cell_lat - half] * 2 + [cell_lat + half] * 2)
    cols = (np.asarray(xs) - transform.c) / brf.CELL_M
    rows = (transform.f - np.asarray(ys)) / brf.CELL_M
    r0, r1 = max(int(rows.min()) - 2, 0), min(int(np.ceil(rows.max())) + 2, shape[0])
    c0, c1 = max(int(cols.min()) - 2, 0), min(int(np.ceil(cols.max())) + 2, shape[1])
    if r0 >= r1 or c0 >= c1:
        return np.empty(0), np.empty(0)
    X, Y = np.meshgrid(transform.c + (np.arange(c0, c1) + 0.5) * brf.CELL_M,
                       transform.f - (np.arange(r0, r1) + 0.5) * brf.CELL_M)
    lon, lat = Transformer.from_crs(brf.GRID_CRS, "EPSG:4326", always_xy=True).transform(X, Y)
    keep = ((snap(lat) == cell_lat) & (snap(lon) == cell_lon) & stable[r0:r1, c0:c1]
            & brf.in_bbox(lon, lat, REGION_BBOX))
    return lon[keep], lat[keep]


# --- terrain scores without regional leakage ---------------------------------------------------

def terrain_scores(points: pd.DataFrame, table: pd.DataFrame, family: gv.Family, log=print) -> pd.Series:
    """Calibrated susceptibility per point from a fit that excludes the point's region and a buffer."""
    table = gv.with_regions(table)
    train = table[table["set"] == "train"]
    points = points.assign(region=gv.region_of(points["lon"], points["lat"]))
    out = pd.Series(np.nan, index=points.index)
    for region in gv.REGIONS:
        mine = points["region"] == region
        if not mine.any():
            continue
        held = np.vstack([gv.xy_of(train[train["region"] == region]), gv.xy_of(points[mine])])
        dist, _ = cKDTree(held).query(gv.xy_of(train), k=1, distance_upper_bound=gv.CV_BUFFER_M)
        keep = (train["region"].to_numpy() != region) & (dist > gv.CV_BUFFER_M)
        fitted = gv.fit_with_validation(train[keep], family, log)
        raw = fitted.scorer.score(points[mine])
        out[mine] = fitted.calibrators["isotonic"].predict(raw)
        log(f"    terrain {region:17s} {int(mine.sum())} points, trained on {int(keep.sum())} rows")
    return out


# --- the design --------------------------------------------------------------------------------

def assemble(points: pd.DataFrame, rows: pd.DataFrame, draw: int) -> pd.DataFrame:
    """The 2 x 2 rows for one case draw."""
    cases = rows[rows["role"] == "case"].set_index("cluster_id")
    controls = rows[rows["role"] == "control"]
    keep_cols = ["cluster_id", "storm_id", "water_year", "sample_water_year", "cell_id", "inventories", "day",
                 *RAIN_COLUMNS]
    case_pts = points[points["point"] == f"case_{draw}"].set_index("cluster_id")
    place_pts = points[points["point"].str.startswith("place_")]
    parts = []
    base = cases.loc[cases.index.intersection(case_pts.index)].reset_index()[keep_cols]
    parts.append(base.assign(kind="case", label=1, point=f"case_{draw}")
                 .merge(case_pts[["s", "precise", "region", "lon", "lat"]], left_on="cluster_id", right_index=True))
    ctl = controls[controls["cluster_id"].isin(case_pts.index)][keep_cols]
    parts.append(ctl.assign(kind="same_place_other_day", label=0, point=f"case_{draw}")
                 .merge(case_pts[["s", "precise", "region", "lon", "lat"]], left_on="cluster_id", right_index=True))
    places = place_pts[["cluster_id", "point", "s", "region", "lon", "lat"]].assign(precise=True)
    parts.append(base.merge(places, on="cluster_id").assign(kind="other_place_same_day", label=0))
    parts.append(ctl.merge(places, on="cluster_id").assign(kind="other_place_other_day", label=0))
    out = pd.concat(parts, ignore_index=True)
    out = out[out["cluster_id"].isin(place_pts["cluster_id"])]  # the full 2 x 2 only
    return out.dropna(subset=["s"]).reset_index(drop=True)


def oof_logistic(rows: pd.DataFrame, columns: list[str], k: int = ev.N_FOLDS) -> np.ndarray:
    """Out-of-fold logistic probabilities, water-year blocks, held-out years dropped from training."""
    sets = rows.drop_duplicates("cluster_id").set_index("cluster_id")[["water_year"]]
    fold_of_set = ev.year_block_folds(sets, k)
    x = rows[columns].to_numpy(float)
    out = np.full(len(rows), np.nan)
    for fold in range(k):
        train, test = ev.train_test_masks(rows, fold_of_set, fold, "year")
        if not test.any() or rows["label"].to_numpy()[train].min() == rows["label"].to_numpy()[train].max():
            continue
        model = LogisticRegression(C=1.0, max_iter=2000).fit(x[train], rows["label"].to_numpy()[train])
        out[test] = model.predict_proba(x[test])[:, 1]
    return out


def score_variants(rows: pd.DataFrame) -> dict[str, np.ndarray]:
    s, r, rp, m = (rows[c].to_numpy(float) for c in ("s", "rainfall_exceedance", "past_72h_exceedance",
                                                    "moisture_index"))
    frame = rows.assign(logit_s=logit(s), logit_s_x_r=logit(s) * r)
    return {
        "terrain_only": s,
        "rain_only_live": sigmoid(W0 + W2 * r + W3 * m),
        "live_combined": live_index(s, r, m),
        "live_combined_no_forecast": live_index(s, rp, m),
        "fitted_additive": oof_logistic(frame, ["logit_s", "rainfall_exceedance", "moisture_index"]),
        "fitted_interaction": oof_logistic(frame, ["logit_s", "rainfall_exceedance", "moisture_index", "logit_s_x_r"]),
    }


def concordance_by_kind(rows: pd.DataFrame, score: np.ndarray) -> dict[str, float]:
    """P(case outranks a control of each kind in its own cluster), ties half."""
    frame = rows[["cluster_id", "kind"]].assign(score=score)
    case = frame[frame["kind"] == "case"].groupby("cluster_id")["score"].first()
    out = {}
    for kind in KINDS:
        ctl = frame[frame["kind"] == kind]
        cs = ctl["cluster_id"].map(case)
        wins = (cs > ctl["score"]).astype(float) + 0.5 * (cs == ctl["score"])
        out[kind] = float(wins.mean()) if len(wins) else float("nan")
    return out


def design_metrics(rows: pd.DataFrame, score: np.ndarray) -> dict:
    ok = ~np.isnan(score)
    labels = rows["label"].to_numpy()[ok]
    out = {**gm.ranking_metrics(labels, score[ok]), **gm.probability_metrics(labels, score[ok])}
    out.update({f"concordance_{k}": v for k, v in concordance_by_kind(rows[ok], score[ok]).items()})
    out["high_bin"] = gm.confusion(labels, score[ok], HIGH_THRESHOLD)
    return out


def storm_bootstrap(rows: pd.DataFrame, preds: dict[str, np.ndarray], reps: int, seed: int = SEED,
                    reference: str = "live_combined") -> dict:
    storms = rows["storm_id"].to_numpy()
    uniq, inverse = np.unique(storms, return_inverse=True)
    members = [np.flatnonzero(inverse == i) for i in range(len(uniq))]
    rng = np.random.default_rng(seed)
    keys = ("roc_auc", "pr_auc", *[f"concordance_{k}" for k in KINDS])
    samples = {name: {k: [] for k in keys} for name in preds}
    deltas = {name: {k: [] for k in keys} for name in preds if name != reference}
    for _ in range(reps):
        pick = np.concatenate([members[i] for i in rng.integers(0, len(uniq), len(uniq))])
        sub = rows.iloc[pick].reset_index(drop=True)
        if not gm.both_classes(sub["label"]):
            continue
        rep = {}
        for name, score in preds.items():
            m = design_metrics(sub, score[pick])
            rep[name] = m
            for k in keys:
                samples[name][k].append(m[k])
        for name in deltas:
            for k in keys:
                deltas[name][k].append(rep[name][k] - rep[reference][k])

    def ci(values):
        arr = np.asarray(values, dtype=float)
        arr = arr[np.isfinite(arr)]
        return [float(np.percentile(arr, 2.5)), float(np.percentile(arr, 97.5))] if arr.size else None

    return {"reps": reps, "storms": int(len(uniq)),
            "ci95": {n: {k: ci(v) for k, v in d.items()} for n, d in samples.items()},
            "delta_vs_live_ci95": {n: {k: ci(v) for k, v in d.items()} for n, d in deltas.items()}}


RAIN_BANDS = [-1.01, -0.5, 0.0, 0.5, 1.01]
TERRAIN_BANDS = [0, 0.1, 0.25, 0.45, 1.0001]


def rain_error_rows(rows: pd.DataFrame, score: np.ndarray, name: str) -> list[dict]:
    """Outcome at the shared 0.45 bin edge by rain, antecedent moisture, terrain, kind and season."""
    frame = rows.assign(score=score, flagged=score >= HIGH_THRESHOLD)
    frame["rain_band"] = pd.cut(frame["rainfall_exceedance"], RAIN_BANDS).astype(str)
    frame["moisture_band"] = pd.cut(frame["moisture_index"], RAIN_BANDS).astype(str)
    frame["terrain_band"] = pd.cut(frame["s"], TERRAIN_BANDS, right=False).astype(str)
    month = pd.to_datetime(frame["day"]).dt.month
    frame["season"] = np.select([month.isin([12, 1, 2]), month.isin([3, 4, 5]), month.isin([6, 7, 8])],
                                ["DJF", "MAM", "JJA"], "SON")
    frame["location"] = np.where(frame["precise"], "precise", "glc_only")
    rows_out = []
    for grouping in ("rain_band", "moisture_band", "terrain_band", "kind", "season", "location", "region"):
        for value, part in frame.groupby(frame[grouping].fillna("unknown")):
            y, f = part["label"].to_numpy(), part["flagged"].to_numpy()
            tp, fp = int((f & (y == 1)).sum()), int((f & (y == 0)).sum())
            fn, tn = int((~f & (y == 1)).sum()), int((~f & (y == 0)).sum())
            rows_out.append({"variant": name, "grouping": grouping, "value": value, "n": len(part), "tp": tp,
                             "fp": fp, "tn": tn, "fn": fn,
                             "recall": tp / (tp + fn) if tp + fn else float("nan"),
                             "false_positive_rate": fp / (fp + tn) if fp + tn else float("nan"),
                             "mean_score": float(part["score"].mean())})
    return rows_out


def counts_by_region(rows_all: pd.DataFrame, records: pd.DataFrame) -> dict:
    """Dated clusters by region, and whether any sits in the Rainier box."""
    clusters = rows_all[rows_all["role"] == "case"]
    in_rainier = brf.in_bbox(records["lon"].to_numpy(), records["lat"].to_numpy(), RAINIER_BBOX)
    regions = gv.region_of(records["lon"], records["lat"])
    per_region = pd.Series(regions).groupby(regions).size().to_dict()
    clusters_per_region = (records.assign(region=regions).drop_duplicates("cluster_id")
                           .groupby("region").size().to_dict())
    return {"clusters": int(clusters["cluster_id"].nunique()), "storms": int(clusters["storm_id"].nunique()),
            "water_years": int(clusters["water_year"].nunique()),
            "records_by_region": {k: int(v) for k, v in per_region.items()},
            "clusters_by_region": {k: int(v) for k, v in clusters_per_region.items()},
            "records_in_rainier_box": int(in_rainier.sum())}


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rebuild-points", action="store_true")
    parser.add_argument("--bootstrap", type=int, default=1000)
    parser.add_argument("--terrain-family", default=DEFAULT_TERRAIN_FAMILY,
                        help="terrain family from geo_validate.py (default: the deployed LightGBM)")
    parser.add_argument("--table", type=Path, default=brf.TABLE_PATH)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    started = time.time()
    log = print
    rows_all, records = load_design()
    log(f"{rows_all['cluster_id'].nunique()} dated clusters with a record in the terrain region")
    if args.rebuild_points or not POINTS_PATH.exists():
        points = build_points(rows_all, records, log)
        points.to_parquet(POINTS_PATH, index=False)
    points = pd.read_parquet(POINTS_PATH)
    points = points[points["valid"]].reset_index(drop=True)
    family = gv.FAMILY_BY_NAME[args.terrain_family]
    points["region"] = gv.region_of(points["lon"], points["lat"])
    points["s"] = terrain_scores(points, pd.read_parquet(args.table), family, log).to_numpy()

    per_draw, primary = [], None
    for draw in range(CASE_DRAWS):
        rows = assemble(points, rows_all, draw)
        preds = score_variants(rows)
        metrics = {name: design_metrics(rows, p) for name, p in preds.items()}
        per_draw.append({"draw": draw, **{f"{n}_{k}": metrics[n][k] for n in preds
                                          for k in ("roc_auc", "pr_auc", "concordance_other_place_same_day",
                                                    "concordance_same_place_other_day")}})
        if draw == 0:
            primary = (rows, preds, metrics)
    rows, preds, metrics = primary
    precise_sets = rows.loc[(rows["kind"] == "case") & rows["precise"], "cluster_id"]
    sub = rows["cluster_id"].isin(precise_sets).to_numpy()
    precise_metrics = {name: design_metrics(rows[sub].reset_index(drop=True), p[sub]) for name, p in preds.items()}
    boot = storm_bootstrap(rows, preds, args.bootstrap)
    fit = LogisticRegression(C=1.0, max_iter=2000).fit(
        np.c_[logit(rows["s"]), rows["rainfall_exceedance"], rows["moisture_index"]], rows["label"])
    errors = []
    for name in ("live_combined", "fitted_additive"):
        errors += rain_error_rows(rows, preds[name], name)

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    gv.write_csv([{"variant": n, **{k: v for k, v in m.items() if k != "high_bin"},
                   **{f"high_{k}": v for k, v in m["high_bin"].items()}} for n, m in metrics.items()],
                 out / "combined_metrics.csv")
    gv.write_csv(per_draw, out / "combined_case_draws.csv")
    gv.write_csv(errors, out / "combined_errors_by_band.csv")
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "design": {"lead_hours": LEAD_HOURS, "control_places": CONTROL_PLACES, "case_draws": CASE_DRAWS,
                   "kinds": list(KINDS), "terrain_family": family.name,
                   "rows": int(len(rows)), "cases": int(rows["label"].sum()), "prevalence": float(rows["label"].mean()),
                   "clusters_in_full_design": int(rows["cluster_id"].nunique()),
                   "clusters_precise_location": int(precise_sets.nunique()),
                   "live_formula": "sigmoid(W1*(logit(s) - logit(0.25)) + W0 + W2*r + W3*m)",
                   "constants": {"W0": W0, "W1": W1, "W2": W2, "W3": W3}},
        "coverage": counts_by_region(rows_all, records),
        "metrics": metrics, "metrics_precise_locations": precise_metrics,
        "storm_bootstrap": boot,
        "case_draw_sensitivity": per_draw,
        "in_sample_fit": {"coef_logit_s": float(fit.coef_[0][0]), "coef_rain": float(fit.coef_[0][1]),
                          "coef_moisture": float(fit.coef_[0][2]), "intercept": float(fit.intercept_[0]),
                          "note": "full-data fit, for the terrain weight only; live W1 is 1"},
        "rainier": "no dated event cluster has a record in the Rainier box; this is not Rainier validation",
        "caveats": [
            "prevalence is set by the design (1 case : 4 control days : 4 places : 16 place-days); "
            "probabilities and the 0.45 bin are not real-world rates",
            "lead-0 rain reads the reanalysis next 72 h, a perfect forecast; see live_combined_no_forecast",
            "GLC-only clusters place the case up to 5 km from the slide; see metrics_precise_locations",
        ],
        "runtime_s": round(time.time() - started, 1),
    }
    (out / "combined_validation.json").write_text(json.dumps(gv.clean(report), indent=2) + "\n")
    for name, m in metrics.items():
        log(f"  {name:26s} ROC {m['roc_auc']:.3f} PR {m['pr_auc']:.3f} lift {m['lift']:.2f} | case beats: "
            + ", ".join(f"{k} {m['concordance_' + k]:.3f}" for k in KINDS))
    log(f"wrote {out / 'combined_validation.json'} in {report['runtime_s']} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
