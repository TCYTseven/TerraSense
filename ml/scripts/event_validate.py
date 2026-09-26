"""Event-time validation of Model B's rain terms, and a grouped out-of-fold fit of its weights.

`python ml/scripts/event_validate.py [--features PATH] [--bootstrap N] [--folds K] [--artifacts DIR]`

Reads the case-crossover table from `event_rain.py`. Every matched set (one event cluster and its
same-cell controls) belongs to its storm's water year. Cross-validation holds out contiguous
blocks of water years: a storm, its clusters, and their controls are never split, and training
also drops every row whose own date falls in a held-out water year. A second scheme holds out
spatial regions instead. Confidence intervals resample whole storms (the unit that shares one
weather system), not rows.

Variants:
- `handset`: live Model B, sigmoid(W1*(s - 0.75) + W2*rain_exceedance + W3*moisture_index) with the
  terrain term at zero (s = 0.75) unless a susceptibility column is present. Not fitted.
- `lr_model_b`: logistic regression with intercept on the same two terms, out-of-fold.
- `gbm_rich`: a small fixed-hyperparameter LightGBM on richer rain, snow, and soil features.
- `*_no_forecast`: the same using only weather before T. The other variants read the reanalysis
  "next 72 h", which is a perfect forecast: an upper bound on live skill.

Writes `ml/artifacts/model_b_validation.json`, and `ml/artifacts/model_b_weights.json` only when
the fitted terms beat the hand-set ones out-of-fold under the rule in `weights_rule()`.
"""

from __future__ import annotations

import argparse
import json
import time
import warnings
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score

REPO_ROOT = Path(__file__).resolve().parents[2]
EVENTS_DIR = REPO_ROOT / "data" / "processed" / "events"
ARTIFACTS = REPO_ROOT / "ml" / "artifacts"

# Live Model B constants, from backend/app/ml/model_b.py.
W1, W2, W3 = 7.0, 2.0, 1.6
SUSCEPTIBILITY_CENTER = 0.75
HIGH_THRESHOLD = 0.45  # shared bins: high starts at 0.45
RISK_BINS = {"low": (0.0, 0.2), "moderate": (0.2, 0.45), "high": (0.45, 0.7), "extreme": (0.7, 1.0)}

MODEL_B_TERMS = ["rainfall_exceedance", "moisture_index"]
NO_FORECAST_TERMS = ["past_72h_exceedance", "moisture_index"]
RICH_FEATURES = [
    "rainfall_exceedance", "moisture_index", "past_72h_exceedance", "next_72h_mm", "past_7d_mm",
    "past_24h_mm", "max_24h_next_72h_mm", "max_24h_past_7d_mm", "max_1h_next_72h_mm",
    "liquid_next_72h_mm", "rain_on_snow_next_72h_mm", "snowfall_past_7d_cm", "temp_mean_past_72h_c",
    "temp_mean_next_72h_c", "soil_moisture_at_t",
]
RICH_NO_FORECAST = [f for f in RICH_FEATURES
                    if not f.startswith(("next_", "max_24h_next", "max_1h_next", "liquid_next",
                                         "rain_on_snow_next", "temp_mean_next", "rainfall_exceedance"))]
GBM_PARAMS = dict(n_estimators=200, learning_rate=0.03, num_leaves=7, min_child_samples=40,
                  subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
                  random_state=0, verbose=-1)
N_FOLDS = 5
N_BOOTSTRAP = 1000
ECE_BINS = 10
REGION_BLOCK_DEG = (1.0, 0.5)  # lon, lat size of the leave-region-out blocks
SEED = 20260926


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -60, 60)))


# ---------- folds ----------

def year_block_folds(sets: pd.DataFrame, k: int = N_FOLDS) -> pd.Series:
    """Fold per matched set: contiguous water-year blocks with roughly equal case counts.

    `sets` has one row per matched set with `water_year`. Every set of one water year (and so
    every cluster of one storm) lands in the same fold.
    """
    per_year = sets.groupby("water_year").size().sort_index()
    cum = per_year.cumsum() / per_year.sum()
    fold_of_year = np.minimum((cum.shift(fill_value=0) * k).astype(int), k - 1)
    return sets.water_year.map(fold_of_year)


def region_folds(sets: pd.DataFrame, k: int = N_FOLDS) -> pd.Series:
    """Fold per matched set by spatial block, blocks dealt to folds greedily by case count."""
    block = (np.floor(sets.cell_lon / REGION_BLOCK_DEG[0]).astype(int).astype(str) + ":"
             + np.floor(sets.cell_lat / REGION_BLOCK_DEG[1]).astype(int).astype(str))
    sizes = block.value_counts()
    load = np.zeros(k)
    fold_of_block = {}
    for name, n in sizes.items():
        f = int(np.argmin(load))
        fold_of_block[name] = f
        load[f] += n
    return block.map(fold_of_block)


def train_test_masks(rows: pd.DataFrame, fold_of_set: pd.Series, fold: int, scheme: str):
    """Rows to test (every row of the held-out matched sets) and rows to train on.

    Year scheme: training also drops rows whose own date is in a held-out water year, so no
    control day from the test years informs the fit. Region scheme: training drops rows whose
    cell sits in a held-out block.
    """
    set_fold = rows.cluster_id.map(fold_of_set)
    test = (set_fold == fold).to_numpy()
    train = ~test
    if scheme == "year":
        held_years = set(rows.loc[test, "water_year"])
        train &= ~rows.sample_water_year.isin(held_years).to_numpy()
    elif scheme == "region":
        held_cells = set(rows.loc[test, "cell_id"])
        train &= ~rows.cell_id.isin(held_cells).to_numpy()
    return train, test


# ---------- models ----------

def handset_logit(rows: pd.DataFrame, terms=MODEL_B_TERMS) -> np.ndarray:
    s = rows["susceptibility"].to_numpy(dtype=float) if "susceptibility" in rows else np.full(len(rows), np.nan)
    terrain = np.where(np.isfinite(s), W1 * (np.clip(s, 0, 1) - SUSCEPTIBILITY_CENTER), 0.0)  # the hand-set baseline
    weights = {"rainfall_exceedance": W2, "moisture_index": W3}
    return terrain + sum(weights[t] * rows[t].to_numpy(dtype=float) for t in terms)


def fit_lr(x: np.ndarray, y: np.ndarray) -> LogisticRegression:
    model = LogisticRegression(C=np.inf, max_iter=1000)  # unpenalized
    model.fit(x, y)
    return model


def fit_gbm(x: pd.DataFrame, y: np.ndarray):
    import lightgbm as lgb

    model = lgb.LGBMClassifier(**GBM_PARAMS)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model.fit(x, y)
    return model


def out_of_fold(rows: pd.DataFrame, fold_of_set: pd.Series, scheme: str, k: int) -> dict[str, np.ndarray]:
    """Out-of-fold probabilities for each fitted variant; hand-set variants need no fitting."""
    y = rows.label.to_numpy()
    preds = {name: np.full(len(rows), np.nan) for name in
             ("lr_model_b", "lr_no_forecast", "gbm_rich", "gbm_rich_no_forecast")}
    train_sizes = []
    for fold in range(k):
        train, test = train_test_masks(rows, fold_of_set, fold, scheme)
        if not test.any():
            continue
        train_sizes.append({"fold": fold, "train_rows": int(train.sum()), "test_rows": int(test.sum()),
                            "train_cases": int(y[train].sum()), "test_cases": int(y[test].sum())})
        for name, cols in (("lr_model_b", MODEL_B_TERMS), ("lr_no_forecast", NO_FORECAST_TERMS)):
            m = fit_lr(rows.loc[train, cols].to_numpy(), y[train])
            preds[name][test] = m.predict_proba(rows.loc[test, cols].to_numpy())[:, 1]
        for name, cols in (("gbm_rich", RICH_FEATURES), ("gbm_rich_no_forecast", RICH_NO_FORECAST)):
            m = fit_gbm(rows.loc[train, cols], y[train])
            preds[name][test] = m.predict_proba(rows.loc[test, cols])[:, 1]
    preds["handset"] = sigmoid(handset_logit(rows))
    preds["handset_no_forecast"] = sigmoid(handset_logit(rows, ["moisture_index"]))
    preds["_folds"] = train_sizes
    return preds


def fit_clr(x: np.ndarray, set_index: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Conditional logistic regression for matched sets: no intercept, location cancels."""
    order = np.argsort(set_index, kind="stable")
    x, set_index, y = x[order], set_index[order], y[order]
    starts = np.flatnonzero(np.r_[True, set_index[1:] != set_index[:-1]])
    case_rows = np.flatnonzero(y == 1)

    def nll(beta):
        eta = x @ beta
        m = np.maximum.reduceat(eta, starts)
        m_rows = np.repeat(m, np.diff(np.r_[starts, len(eta)]))
        e = np.exp(eta - m_rows)
        denom = np.add.reduceat(e, starts)
        value = -(eta[case_rows].sum() - (np.log(denom) + m).sum())
        w = e / np.repeat(denom, np.diff(np.r_[starts, len(eta)]))
        grad = -(x[case_rows].sum(axis=0) - np.add.reduceat(w[:, None] * x, starts).sum(axis=0))
        return value, grad

    result = minimize(nll, np.zeros(x.shape[1]), jac=True, method="BFGS")
    return result.x


# ---------- metrics ----------

def ece(y: np.ndarray, p: np.ndarray, bins: int = ECE_BINS) -> float:
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    total = 0.0
    for b in range(bins):
        mask = idx == b
        if mask.any():
            total += mask.mean() * abs(y[mask].mean() - p[mask].mean())
    return float(total)


def reliability(y: np.ndarray, p: np.ndarray, bins: int = ECE_BINS) -> list[dict]:
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    out = []
    for b in range(bins):
        mask = idx == b
        if mask.any():
            out.append({"bin": [round(edges[b], 2), round(edges[b + 1], 2)], "n": int(mask.sum()),
                        "mean_predicted": round(float(p[mask].mean()), 4),
                        "observed_rate": round(float(y[mask].mean()), 4)})
    return out


def point_metrics(y: np.ndarray, p: np.ndarray, threshold: float = HIGH_THRESHOLD) -> dict[str, float]:
    pred = p >= threshold
    tp = float((pred & (y == 1)).sum())
    fp = float((pred & (y == 0)).sum())
    fn = float((~pred & (y == 1)).sum())
    tn = float((~pred & (y == 0)).sum())
    precision = tp / (tp + fp) if tp + fp else np.nan
    recall = tp / (tp + fn) if tp + fn else np.nan
    specificity = tn / (tn + fp) if tn + fp else np.nan
    f1 = 2 * precision * recall / (precision + recall) if precision + recall and np.isfinite(precision) else np.nan
    pc = np.clip(p, 1e-6, 1 - 1e-6)
    return {
        "roc_auc": float(roc_auc_score(y, p)), "pr_auc": float(average_precision_score(y, p)),
        "base_rate": float(y.mean()), "brier": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, pc, labels=[0, 1])),
        "balanced_accuracy": float((recall + specificity) / 2), "precision_at_0.45": precision,
        "recall_at_0.45": recall, "f1_at_0.45": f1, "ece": ece(y, p),
        "mean_predicted": float(p.mean()),
    }


def matched_concordance_parts(rows: pd.DataFrame, score: np.ndarray) -> pd.DataFrame:
    """Per matched set: case-beats-control pairs (ties count half) and pair count."""
    frame = pd.DataFrame({"set": rows.cluster_id.to_numpy(), "y": rows.label.to_numpy(), "s": score})
    case = frame[frame.y == 1].set_index("set").s
    ctrl = frame[frame.y == 0]
    cs = ctrl.set.map(case)
    wins = (cs > ctrl.s).astype(float) + 0.5 * (cs == ctrl.s)
    return pd.DataFrame({"wins": wins.groupby(ctrl.set).sum(), "pairs": ctrl.groupby("set").size()})


def bootstrap(rows: pd.DataFrame, preds: dict[str, np.ndarray], n: int, seed: int = SEED,
              reference: str = "handset") -> dict:
    """Storm-level bootstrap of every metric and of the difference from the hand-set variant."""
    rng = np.random.default_rng(seed)
    storms = rows.storm_id.to_numpy()
    uniq, inv = np.unique(storms, return_inverse=True)
    members = [np.flatnonzero(inv == i) for i in range(len(uniq))]
    y = rows.label.to_numpy()
    names = [k for k in preds if not k.startswith("_")]
    conc = {k: matched_concordance_parts(rows, preds[k]) for k in names}
    set_storm = rows.drop_duplicates("cluster_id").set_index("cluster_id").storm_id
    storm_sets = {s: set_storm.index[set_storm == s] for s in uniq}
    samples = {k: [] for k in names}
    deltas = {k: [] for k in names if k != reference}
    for _ in range(n):
        pick = rng.integers(0, len(uniq), len(uniq))
        idx = np.concatenate([members[i] for i in pick])
        if y[idx].min() == y[idx].max():
            continue
        sets = np.concatenate([storm_sets[uniq[i]].to_numpy() for i in pick])
        rep = {}
        for k in names:
            m = point_metrics(y[idx], preds[k][idx])
            c = conc[k].reindex(sets)
            m["matched_concordance"] = float(c.wins.sum() / c.pairs.sum())
            samples[k].append(m)
            rep[k] = m
        for k in deltas:
            deltas[k].append({f"delta_{m}": rep[k][m] - rep[reference][m]
                              for m in ("roc_auc", "pr_auc", "brier", "log_loss", "matched_concordance")})

    def summarize(values: list[dict]) -> dict:
        frame = pd.DataFrame(values)
        return {c: [float(np.nanpercentile(frame[c], 2.5)), float(np.nanpercentile(frame[c], 97.5))]
                for c in frame.columns}

    return {"ci95": {k: summarize(v) for k, v in samples.items()},
            "delta_vs_handset_ci95": {k: summarize(v) for k, v in deltas.items()},
            "delta_vs_handset_mean": {k: pd.DataFrame(v).mean().to_dict() for k, v in deltas.items()},
            "n_reps": len(next(iter(samples.values()))), "n_storms": int(len(uniq))}


def full_metrics(rows: pd.DataFrame, preds: dict[str, np.ndarray]) -> dict:
    y = rows.label.to_numpy()
    out = {}
    for k, p in preds.items():
        if k.startswith("_"):
            continue
        m = point_metrics(y, p)
        c = matched_concordance_parts(rows, p)
        m["matched_concordance"] = float(c.wins.sum() / c.pairs.sum())
        out[k] = m
    return out


def coefficient_bootstrap(rows: pd.DataFrame, n: int, seed: int = SEED) -> dict:
    """LR (with intercept) and conditional LR coefficients on all rows, storm-bootstrap CIs."""
    rng = np.random.default_rng(seed + 1)
    x = rows[MODEL_B_TERMS].to_numpy()
    y = rows.label.to_numpy()
    sets = pd.factorize(rows.cluster_id)[0]
    lr = fit_lr(x, y)
    clr = fit_clr(x, sets, y)
    uniq, inv = np.unique(rows.storm_id.to_numpy(), return_inverse=True)
    members = [np.flatnonzero(inv == i) for i in range(len(uniq))]
    lr_reps, clr_reps = [], []
    for r in range(n):
        pick = rng.integers(0, len(uniq), len(uniq))
        idx = np.concatenate([members[i] for i in pick])
        # Repeated storms become distinct matched sets so the conditional likelihood stays per set.
        rep_sets = np.concatenate([sets[members[i]] + (j + 1) * (sets.max() + 1) for j, i in enumerate(pick)])
        if y[idx].min() == y[idx].max():
            continue
        m = fit_lr(x[idx], y[idx])
        lr_reps.append([m.intercept_[0], *m.coef_[0]])
        clr_reps.append(fit_clr(x[idx], rep_sets, y[idx]))
    lr_reps, clr_reps = np.array(lr_reps), np.array(clr_reps)

    def ci(a):
        return [float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5))]

    return {
        "logistic_with_intercept": {
            "intercept": float(lr.intercept_[0]), "w2_rainfall_exceedance": float(lr.coef_[0][0]),
            "w3_moisture_index": float(lr.coef_[0][1]),
            "ci95": {"intercept": ci(lr_reps[:, 0]), "w2_rainfall_exceedance": ci(lr_reps[:, 1]),
                     "w3_moisture_index": ci(lr_reps[:, 2])},
        },
        "conditional_logistic": {
            "w2_rainfall_exceedance": float(clr[0]), "w3_moisture_index": float(clr[1]),
            "ci95": {"w2_rainfall_exceedance": ci(clr_reps[:, 0]), "w3_moisture_index": ci(clr_reps[:, 1])},
        },
        "handset": {"w2": W2, "w3": W3},
        "handset_inside_ci95": {
            "logistic_w2": bool(ci(lr_reps[:, 1])[0] <= W2 <= ci(lr_reps[:, 1])[1]),
            "logistic_w3": bool(ci(lr_reps[:, 2])[0] <= W3 <= ci(lr_reps[:, 2])[1]),
            "conditional_w2": bool(ci(clr_reps[:, 0])[0] <= W2 <= ci(clr_reps[:, 0])[1]),
            "conditional_w3": bool(ci(clr_reps[:, 1])[0] <= W3 <= ci(clr_reps[:, 1])[1]),
        },
        "n_reps": int(len(lr_reps)),
    }


def weights_rule(boot: dict) -> tuple[bool, str]:
    """Fixed before any result was seen: the fit must lower the out-of-fold Brier score with a
    storm-bootstrap 95% CI entirely below zero, and must not lower pooled ROC-AUC or the
    within-set (ratio-free) matched concordance on average."""
    d_ci = boot["delta_vs_handset_ci95"]["lr_model_b"]
    d_mean = boot["delta_vs_handset_mean"]["lr_model_b"]
    ok = (d_ci["delta_brier"][1] < 0 and d_mean["delta_roc_auc"] >= 0
          and d_mean["delta_matched_concordance"] >= 0)
    why = (f"delta Brier CI {[round(v, 4) for v in d_ci['delta_brier']]}, mean delta ROC-AUC "
           f"{d_mean['delta_roc_auc']:+.4f}, mean delta matched concordance "
           f"{d_mean['delta_matched_concordance']:+.4f}; rule: Brier CI upper < 0, mean delta ROC-AUC >= 0, "
           "mean delta matched concordance >= 0")
    return ok, why


def rounded(obj, places: int = 4):
    if isinstance(obj, float):
        return None if not np.isfinite(obj) else round(obj, places)
    if isinstance(obj, dict):
        return {k: rounded(v, places) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [rounded(v, places) for v in obj]
    if isinstance(obj, (np.floating,)):
        return rounded(float(obj), places)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    return obj


def evaluate(rows: pd.DataFrame, scheme: str, k: int, n_boot: int) -> dict:
    sets = rows.drop_duplicates("cluster_id").set_index("cluster_id")
    fold_of_set = year_block_folds(sets, k) if scheme == "year" else region_folds(sets, k)
    preds = out_of_fold(rows, fold_of_set, scheme, k)
    folds = preds["_folds"]
    if scheme == "year":
        for f in folds:
            f["water_years"] = sorted(int(w) for w in sets.water_year[fold_of_set == f["fold"]].unique())
    result = {"folds": folds, "metrics": full_metrics(rows, preds)}
    if n_boot:
        result["bootstrap"] = bootstrap(rows, preds, n_boot)
    result["_preds"] = preds
    return result


def usable_rows(table: pd.DataFrame, lead: int) -> tuple[pd.DataFrame, dict]:
    rows = table[table.lead_hours == lead].copy()
    per_set = rows.groupby("cluster_id").label.agg(["sum", "size"])
    keep = per_set.index[(per_set["sum"] == 1) & (per_set["size"] >= 2)]
    dropped = int(len(per_set) - len(keep))
    rows = rows[rows.cluster_id.isin(keep)].reset_index(drop=True)
    return rows, {"matched_sets_without_controls_dropped": dropped}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--features", type=Path, default=EVENTS_DIR / "features.parquet")
    parser.add_argument("--artifacts", type=Path, default=ARTIFACTS)
    parser.add_argument("--folds", type=int, default=N_FOLDS)
    parser.add_argument("--bootstrap", type=int, default=N_BOOTSTRAP)
    args = parser.parse_args(argv)
    started = time.monotonic()

    table = pd.read_parquet(args.features)
    rows, drop_info = usable_rows(table, 0)
    y = rows.label.to_numpy()
    n_cases, n_controls = int(y.sum()), int((1 - y).sum())
    print(f"lead 0: {n_cases} cases, {n_controls} controls, {rows.storm_id.nunique()} storms, "
          f"{rows.water_year.nunique()} water years; {drop_info}", flush=True)

    primary = evaluate(rows, "year", args.folds, args.bootstrap)
    region = evaluate(rows, "region", args.folds, max(200, args.bootstrap // 5))
    coefs = coefficient_bootstrap(rows, args.bootstrap)

    sensitivity = {}
    for lead in (24, 48):
        r, _ = usable_rows(table, lead)
        e = evaluate(r, "year", args.folds, 0)
        sensitivity[f"lead_{lead}h"] = {k: e["metrics"][k] for k in ("handset", "lr_model_b", "lr_no_forecast",
                                                                      "gbm_rich", "gbm_rich_no_forecast")}
    big_wgs = {"storm_20071203", "storm_20090107"}
    r = rows[~rows.storm_id.isin(big_wgs)].reset_index(drop=True)
    e = evaluate(r, "year", args.folds, 0)
    sensitivity["without_2007_2009_wgs_storms"] = {
        "n_cases": int(r.label.sum()), **{k: e["metrics"][k] for k in ("handset", "lr_model_b", "gbm_rich")}}
    for src in ("usgs_v3", "nasa_glc"):
        mask = rows.groupby("cluster_id").sources.transform("first").str.contains(src)
        r = rows[mask].reset_index(drop=True)
        e = evaluate(r, "year", args.folds, 0)
        sensitivity[f"only_{src}_clusters"] = {"n_cases": int(r.label.sum()),
                                               **{k: e["metrics"][k] for k in ("handset", "lr_model_b")}}
    r = rows[rows.month_offset.fillna(0) == 0]
    r, _ = usable_rows(r, 0)
    e = evaluate(r, "year", args.folds, 0)
    sensitivity["same_calendar_month_controls_only"] = {
        "n_cases": int(r.label.sum()), **{k: e["metrics"][k] for k in ("handset", "lr_model_b")}}

    preds = primary.pop("_preds")
    region.pop("_preds")
    calibration = {k: {"ece": primary["metrics"][k]["ece"], "reliability": reliability(y, preds[k])}
                   for k in ("handset", "lr_model_b", "gbm_rich")}
    # Share of cases and controls the live hand-set model puts in each shared risk bin.
    bins = {}
    for k in ("handset", "lr_model_b"):
        p = preds[k]
        bins[k] = {role: {name: float(((p >= lo) & (p < hi if hi < 1 else p <= hi))[y == lab].mean())
                          for name, (lo, hi) in RISK_BINS.items()}
                   for role, lab in (("cases", 1), ("controls", 0))}

    catalog = json.loads((args.features.parent / "catalog_summary.json").read_text())
    fetch = json.loads((args.features.parent / "fetch_log.json").read_text())
    n_cells = catalog["n_cells"]
    n_years = catalog["years"][1] - catalog["years"][0] + 1
    windows_per_cell = n_years * 365.25 / 3
    rate = {
        "catalogued_clusters_per_event_cell_year": catalog["n_clusters"] / (n_cells * n_years),
        "catalogued_clusters_per_event_cell_72h": catalog["n_clusters"] / (n_cells * windows_per_cell),
        "note": ("Counts only catalogued clusters in cells that have at least one (selection inflates it; "
                 "catalog incompleteness deflates it, by an unknown and location-dependent amount). "
                 "The unit is a ~0.1 degree weather cell (~80 km2), not a 30 m pixel. This is NOT a "
                 "defensible absolute 72-hour hazard rate, so no absolute recalibration is published."),
    }

    ok, why = weights_rule(primary["bootstrap"])
    report = {
        "generated": str(date.today()),
        "question": "Does Model B's rain signal separate landslide days from same-place other days?",
        "design": {
            "type": "case-crossover (matched sets: one event cluster + same weather cell at other times)",
            "reference_time": "T = event day 00:00 UTC minus lead; lead 0 primary, 24 h and 48 h sensitivity. "
                              "Event day is local (Pacific), so the event falls inside [T, T+72h).",
            "controls": fetch.get("controls_per_case_requested"),
            "control_rule": "same cell; one fixed random day per (year, month); other years; same calendar "
                            "month first, then adjacent months only when a dense cell exhausted them; never "
                            "within 7 days of any dated landslide record within 25 km (any type or trigger); "
                            "never reused by two matched sets",
            "cv_primary": f"{args.folds} contiguous water-year blocks; storms, clusters and matched sets never "
                          "split; training drops rows dated in held-out water years",
            "cv_secondary": f"{args.folds} spatial folds of {REGION_BLOCK_DEG[0]} x {REGION_BLOCK_DEG[1]} deg "
                            "blocks; training drops held-out cells",
            "uncertainty": f"{args.bootstrap} storm-level bootstrap replicates of the out-of-fold predictions",
            "weather": "Open-Meteo archive (ERA5/ERA5-Land reanalysis, best_match) at the 0.1 deg cell center, "
                       "hourly, default elevation",
            "perfect_forecast": "variants without '_no_forecast' use reanalysis rain in [T, T+72h): an upper "
                                "bound on what the live forecast can deliver",
            "susceptibility": ("constant within a matched set, so it cannot change within-set ranking and W1 is "
                               "not identifiable in this design; the hand-set terrain term is held at 0 "
                               "(s = 0.75) unless event_rain.py was given --susceptibility-raster"),
            "susceptibility_coverage": float(rows.susceptibility.notna().mean()),
            "gbm_hyperparameters": GBM_PARAMS,
            "gbm_features": RICH_FEATURES, "gbm_no_forecast_features": RICH_NO_FORECAST,
        },
        "catalog": catalog,
        "fetch": fetch,
        "counts": {"n_cases": n_cases, "n_controls": n_controls, "case_control_ratio": f"1:{n_controls / n_cases:.2f}",
                   "base_rate": n_cases / (n_cases + n_controls), "n_storms": int(rows.storm_id.nunique()),
                   "n_water_years": int(rows.water_year.nunique()), "n_cells": int(rows.cell_id.nunique()),
                   "date_range": [str(rows.day.min().date()), str(rows.day.max().date())], **drop_info,
                   "controls_from_adjacent_month": int((rows.month_offset.fillna(0) != 0).sum())},
        "primary_year_blocked": primary,
        "secondary_region_blocked": region,
        "coefficients": coefs,
        "calibration": calibration,
        "risk_bin_shares": bins,
        "sensitivity": sensitivity,
        "absolute_rate": rate,
        "weights_published": ok,
        "weights_rule": why,
        "caveats": [
            "Probabilities are conditional on the case:control sampling ratio; they are not absolute 72-hour "
            "landslide probabilities.",
            "Next-72h rain is reanalysis (perfect forecast). Live skill with a real forecast is lower; the "
            "no-forecast variants bound it from below.",
            "ERA5 at ~10-30 km smooths orographic rain; the live model reads a forecast downscaled to Paradise "
            "(1650 m). Rain distributions differ, so thresholds and weights may not transfer exactly.",
            "Events are mostly lowland western Washington and Portland, not Mount Rainier; the Rainier box has "
            "very few dated rain-triggered events.",
            "Storm reconnaissance inventories (2007-12-03, 2009-01-07) were mapped because of the storm: they are "
            "real storm-day slides but over-represent big storms. See the sensitivity without them.",
            "Catalogs are incomplete: some control days had unrecorded slides. That biases skill toward zero.",
            "The unit is a ~0.1 deg cell; the live map is 30 m. This validates the rain trigger only, not the "
            "spatial pattern.",
        ],
        "runtime_s": round(time.monotonic() - started, 1),
    }
    args.artifacts.mkdir(parents=True, exist_ok=True)
    (args.artifacts / "model_b_validation.json").write_text(json.dumps(rounded(report), indent=2))
    weights_path = args.artifacts / "model_b_weights.json"
    if ok:
        lr = coefs["logistic_with_intercept"]
        weights = {
            "w1": None, "w1_note": "not identifiable in a case-crossover design; keep the terrain term separate",
            "w2": lr["w2_rainfall_exceedance"], "w3": lr["w3_moisture_index"], "intercept": lr["intercept"],
            "intercept_note": (f"fitted at a 1:{n_controls / n_cases:.2f} case:control ratio; it sets relative, "
                               "not absolute, probability"),
            "susceptibility_center": None,
            "ci95": lr["ci95"], "conditional_logistic": coefs["conditional_logistic"],
            "fitted_on": f"{rows.day.min().date()}..{rows.day.max().date()} western WA / NW OR, ERA5 archive",
            "n_cases": n_cases, "n_controls": n_controls,
            "cv_metrics": {k: primary["metrics"]["lr_model_b"][k] for k in ("roc_auc", "pr_auc", "brier", "ece")},
            "cv_metrics_ci95": primary["bootstrap"]["ci95"]["lr_model_b"],
            "handset_cv_metrics": {k: primary["metrics"]["handset"][k] for k in ("roc_auc", "pr_auc", "brier", "ece")},
            "rule": why,
        }
        weights_path.write_text(json.dumps(rounded(weights), indent=2))
    elif weights_path.exists():
        weights_path.unlink()

    m = primary["metrics"]
    ci = primary["bootstrap"]["ci95"]
    print(f"{'variant':22s} {'ROC-AUC':>20s} {'PR-AUC':>20s} {'Brier':>20s} {'matched C':>20s} {'ECE':>6s}")
    for k in m:
        def cell(metric):
            return f"{m[k][metric]:.3f} [{ci[k][metric][0]:.3f},{ci[k][metric][1]:.3f}]"
        print(f"{k:22s} {cell('roc_auc'):>20s} {cell('pr_auc'):>20s} {cell('brier'):>20s} "
              f"{cell('matched_concordance'):>20s} {m[k]['ece']:6.3f}")
    print("coefficients:", json.dumps(rounded(coefs), indent=None)[:900])
    print("weights published:", ok, "-", why)
    print(f"wrote {args.artifacts / 'model_b_validation.json'} in {time.monotonic() - started:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
