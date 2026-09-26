"""Distribution-shift diagnostics and region-aware error analysis for the selected family.

Called by `geo_validate.py` (skip with `--skip-diagnostics`). Nothing here fits a model that
scores a held-out row or changes a threshold; it explains the numbers LORO and Rainier produced.

Shift, per held-out region (and Rainier against all training rows):
  - Per feature: SMD, PSI, KS, std-scaled Wasserstein, and the share of held-out values outside
    the training 1st-99th percentile range (extrapolation).
  - A domain classifier (small LightGBM, stratified 5-fold) that tells held-out rows from training
    rows. Its ROC-AUC is the overall size of the covariate shift.
  - Covariate shift versus genuine failure: the inner validation scores (training regions only)
    are re-weighted by the domain classifier's density ratio p/(1-p), which estimates how the
    model would rank in the held-out region if only the features had moved. If the real held-out
    ROC-AUC falls well below that estimate, feature shift does not explain the drop: the labels
    behave differently there (mapping practice, landslide types) or the model misses a process.

Errors: TP, FP, TN and FN by slope band, elevation band, land cover, landform (TPI class),
wetness, positive confidence and region; FP-vs-TN and FN-vs-TP feature contrasts; 5 km cells
with the most errors; and the coordinates of the highest-confidence false positives and
false negatives. The terrain rows carry no rainfall, so rain errors are in combined_validate.py.
"""

from __future__ import annotations

from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold

import geo_metrics as gm
import geo_validate as gv
import train_regional_susceptibility as trs

SHIFT_FEATURES = gv.MODEL_FEATURES + ("elevation",)
DOMAIN_PARAMS = {**trs.BASE_PARAMS, "n_estimators": 200, "num_leaves": 7, "min_child_samples": 100}
DOMAIN_FOLDS = 5
WEIGHT_CLIP_QUANTILE = 0.99
# Held-out ROC-AUC this far below the shift-weighted validation estimate counts as a drop that
# covariate shift does not explain.
UNEXPLAINED_GAP = 0.03
MIN_EFFECTIVE_SAMPLE = 200
TOP_ERRORS = 50
CLUSTER_CELL_M = 5000
TOP_CELLS = 20

SLOPE_BANDS = [-np.inf, 10, 20, 30, 40, np.inf]
ELEVATION_BANDS = [-np.inf, 300, 600, 1000, 1500, np.inf]
LANDCOVER_NAMES = {10: "tree", 20: "shrub", 30: "grass", 40: "crop", 50: "built", 60: "bare",
                   70: "snow_ice", 80: "water", 90: "wetland", 95: "mangrove", 100: "moss"}
LANDFORM_EDGES = [-np.inf, -1.0, -0.5, 0.5, 1.0, np.inf]  # tpi_500 in training standard deviations
LANDFORM_NAMES = ["valley", "lower_slope", "mid_slope_or_flat", "upper_slope", "ridge"]


# --- shift -------------------------------------------------------------------------------------

def feature_shift_rows(reference: pd.DataFrame, target: pd.DataFrame, name: str) -> list[dict]:
    rows = []
    for feature in SHIFT_FEATURES:
        ref, tgt = reference[feature].to_numpy(float), target[feature].to_numpy(float)
        categorical = feature == gv.CATEGORICAL
        stats = gm.shift_statistics(ref, tgt, categorical=categorical)
        lo, hi = np.percentile(ref, [1, 99])
        rows.append({"target": name, "feature": feature, **stats,
                     "reference_mean": float(ref.mean()), "target_mean": float(tgt.mean()),
                     "outside_reference_p1_p99": float("nan") if categorical else float(((tgt < lo) | (tgt > hi)).mean())})
    return rows


def domain_scores(reference: pd.DataFrame, target: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, float]:
    """Out-of-fold P(target) for reference and target rows, and the domain ROC-AUC.

    Folds are stratified random, not spatial: the question is whether the two feature
    distributions differ, and spatial folds would turn it into extrapolation across space (a
    compact target region split into blocks scores below 0.5).
    """
    both = pd.concat([reference, target])
    domain = np.r_[np.zeros(len(reference)), np.ones(len(target))].astype(int)
    frame = trs.as_frame(both, list(gv.MODEL_FEATURES))
    oof = np.zeros(len(both))
    splitter = StratifiedKFold(DOMAIN_FOLDS, shuffle=True, random_state=gv.RANDOM_SEED)
    for train_idx, test_idx in splitter.split(frame, domain):
        model = lgb.LGBMClassifier(**DOMAIN_PARAMS).fit(frame.iloc[train_idx], domain[train_idx])
        oof[test_idx] = model.predict_proba(frame.iloc[test_idx])[:, 1]
    auc = float(roc_auc_score(domain, oof))
    return oof[:len(reference)], oof[len(reference):], auc


def shift_vs_failure(reference: pd.DataFrame, target: pd.DataFrame, validation: dict, actual_scores: np.ndarray,
                     name: str) -> dict:
    """Domain AUC, shift-weighted validation ROC-AUC, and held-out ROC-AUC inside and outside support."""
    p_ref, p_tgt, domain_auc = domain_scores(reference, target)
    ref_p = pd.Series(p_ref, index=reference.index)
    val_index, val_labels, val_scores = validation["index"], validation["labels"], validation["scores"]
    p_val = np.clip(ref_p.reindex(val_index).to_numpy(), 1e-4, 1 - 1e-4)
    weights = p_val / (1 - p_val)
    weights = np.minimum(weights, np.quantile(weights, WEIGHT_CLIP_QUANTILE))
    ess = float(weights.sum() ** 2 / (weights ** 2).sum())
    internal = float(roc_auc_score(val_labels, val_scores))
    expected = float(roc_auc_score(val_labels, val_scores, sample_weight=weights))
    labels = target["label"].to_numpy()
    actual = gm.ranking_metrics(labels, actual_scores)["roc_auc"]
    support = p_tgt <= np.quantile(p_ref, 0.99)
    inside = gm.ranking_metrics(labels[support], actual_scores[support])
    outside = gm.ranking_metrics(labels[~support], actual_scores[~support])
    gap = expected - actual
    if ess < MIN_EFFECTIVE_SAMPLE:
        verdict = "undetermined: too few training rows resemble this region to reweight"
    elif actual >= internal - UNEXPLAINED_GAP:
        verdict = "no material drop"
    elif gap <= UNEXPLAINED_GAP:
        verdict = "drop explained by covariate shift"
    else:
        verdict = "drop beyond covariate shift: label or process difference, or model failure"
    positives = target[target["label"] == 1]
    return {
        "target": name, "n": int(len(target)), "positives": int(labels.sum()), "prevalence": float(labels.mean()),
        "domain_auc": domain_auc, "internal_validation_roc_auc": internal,
        "shift_weighted_validation_roc_auc": expected, "heldout_roc_auc": actual,
        "drop_explained_by_shift": internal - expected, "unexplained_gap": gap,
        "effective_sample_size": ess, "verdict": verdict,
        "share_in_support": float(support.mean()), "roc_auc_in_support": inside["roc_auc"],
        "roc_auc_out_of_support": outside["roc_auc"], "n_out_of_support": int((~support).sum()),
        "positives_confidence_ge5_share": float((positives["confidence"] >= 5).mean()) if len(positives) else float("nan"),
        "positives_non_wa_wgs_share": float((positives["source"] != "WA WGS").mean()) if len(positives) else float("nan"),
    }


# --- errors ------------------------------------------------------------------------------------

def outcome(labels: np.ndarray, scores: np.ndarray, thresholds: np.ndarray) -> np.ndarray:
    flagged = scores >= thresholds
    return np.select([flagged & (labels == 1), flagged & (labels == 0), ~flagged & (labels == 0)],
                     ["TP", "FP", "TN"], "FN")


def annotate(frame: pd.DataFrame, tpi_scale: float) -> pd.DataFrame:
    out = frame.copy()
    out["slope_band"] = pd.cut(out["slope"], SLOPE_BANDS, right=False).astype(str)
    out["elevation_band"] = pd.cut(out["elevation"], ELEVATION_BANDS, right=False).astype(str)
    out["landcover_class"] = out["landcover"].fillna(0).astype(int).map(LANDCOVER_NAMES).fillna("unknown")
    out["landform"] = pd.cut(out["tpi_500"] / tpi_scale, LANDFORM_EDGES, labels=LANDFORM_NAMES).astype(str)
    out["wetness_band"] = pd.qcut(out["twi"], 4, labels=["twi_q1_dry", "twi_q2", "twi_q3", "twi_q4_wet"],
                                  duplicates="drop").astype(str)
    out["positive_confidence"] = np.where(out["label"] == 1, out["confidence"].fillna(0).astype(int).astype(str),
                                          "negative")
    return out


GROUPINGS = ("region", "slope_band", "elevation_band", "landcover_class", "landform", "wetness_band",
             "positive_confidence")


def band_rows(frame: pd.DataFrame, scheme: str) -> list[dict]:
    totals = frame["outcome"].value_counts()
    rows = []
    for grouping in GROUPINGS:
        for value, part in frame.groupby(frame[grouping].fillna("unknown"), sort=True):
            counts = part["outcome"].value_counts()
            tp, fp, tn, fn = (int(counts.get(k, 0)) for k in ("TP", "FP", "TN", "FN"))
            rows.append({
                "scheme": scheme, "grouping": grouping, "value": value, "n": len(part),
                "prevalence": float(part["label"].mean()), "tp": tp, "fp": fp, "tn": tn, "fn": fn,
                "precision": tp / (tp + fp) if tp + fp else float("nan"),
                "recall": tp / (tp + fn) if tp + fn else float("nan"),
                "false_positive_rate": fp / (fp + tn) if fp + tn else float("nan"),
                "share_of_all_fp": fp / totals.get("FP", 1) if totals.get("FP", 0) else float("nan"),
                "share_of_all_fn": fn / totals.get("FN", 1) if totals.get("FN", 0) else float("nan"),
                "mean_score": float(part["score"].mean()),
            })
    return rows


def contrast_rows(frame: pd.DataFrame, scheme: str) -> list[dict]:
    rows = []
    for error, correct in (("FP", "TN"), ("FN", "TP")):
        a, b = frame[frame["outcome"] == error], frame[frame["outcome"] == correct]
        if len(a) < 2 or len(b) < 2:
            continue
        for feature in SHIFT_FEATURES:
            if feature == gv.CATEGORICAL:
                continue
            rows.append({"scheme": scheme, "comparison": f"{error}_vs_{correct}", "feature": feature,
                         f"mean_{error.lower()}": float(a[feature].mean()), "mean_correct": float(b[feature].mean()),
                         "smd": gm.standardized_mean_difference(b[feature], a[feature])})
    return rows


def cluster_rows(frame: pd.DataFrame, scheme: str) -> list[dict]:
    cells = trs.block_ids(frame["x"], frame["y"], CLUSTER_CELL_M)
    grouped = frame.assign(cell=cells).groupby("cell")
    table = grouped.agg(n=("label", "size"), fp=("outcome", lambda s: int((s == "FP").sum())),
                        fn=("outcome", lambda s: int((s == "FN").sum())), lon=("lon", "mean"), lat=("lat", "mean"),
                        region=("region", "first")).reset_index()
    rows = []
    for kind in ("fp", "fn"):
        top = table[table[kind] > 0].sort_values([kind, "n"], ascending=[False, True]).head(TOP_CELLS)
        for _, r in top.iterrows():
            rows.append({"scheme": scheme, "error": kind.upper(), "cell_id": int(r["cell"]), "lon": r["lon"],
                         "lat": r["lat"], "region": r["region"], "n": int(r["n"]), "fp": int(r["fp"]),
                         "fn": int(r["fn"])})
    return rows


TOP_COLUMNS = ["lon", "lat", "region", "label", "score", "probability", "slope", "elevation", "landcover_class",
               "relief_500", "tpi_500", "twi", "dist_drainage", "source", "confidence", "dist_any_record_m"]


def top_errors(frame: pd.DataFrame, scheme: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    columns = [c for c in TOP_COLUMNS if c in frame]
    fp = frame[frame["label"] == 0].sort_values("score", ascending=False, kind="stable").head(TOP_ERRORS)
    fn = frame[frame["label"] == 1].sort_values("score", ascending=True, kind="stable").head(TOP_ERRORS)
    return (fp[columns].assign(scheme=scheme, rank=np.arange(1, len(fp) + 1)),
            fn[columns].assign(scheme=scheme, rank=np.arange(1, len(fn) + 1)))


# --- plots (optional: skipped when matplotlib is missing) --------------------------------------

def plots(out: Path, train: pd.DataFrame, loro: dict, family: str, per_region: pd.DataFrame,
          reliability: pd.DataFrame, shift: pd.DataFrame, log=print) -> list[str]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from sklearn.metrics import precision_recall_curve
    except ImportError:
        log("    matplotlib not installed: plots skipped")
        return []
    plot_dir = out / "plots"
    plot_dir.mkdir(exist_ok=True)
    written = []

    fig, ax = plt.subplots(figsize=(7, 5))
    pooled = loro[family]["pooled"]
    for region in gv.REGIONS:
        rows = train["region"] == region
        labels, scores = train.loc[rows, "label"].to_numpy(), pooled.loc[rows, "raw"].to_numpy(float)
        precision, recall, _ = precision_recall_curve(labels, scores)
        line, = ax.plot(recall, precision, label=f"{region} (prev {labels.mean():.2f})")
        ax.axhline(labels.mean(), color=line.get_color(), ls=":", lw=0.8)
    ax.set(xlabel="recall", ylabel="precision", title=f"LORO precision-recall, {family} (dotted: prevalence)",
           xlim=(0, 1), ylim=(0, 1))
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(plot_dir / "pr_curves_loro.png", dpi=120)
    written.append("plots/pr_curves_loro.png")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(6, 5))
    for fam, part in per_region.groupby("family"):
        ax.scatter(part["prevalence"], part["pr_auc"], label=fam, s=18)
    grid = np.linspace(0, 0.4, 5)
    ax.plot(grid, grid, "k:", lw=0.8, label="no skill (PR-AUC = prevalence)")
    ax.set(xlabel="held-out region prevalence", ylabel="PR-AUC", title="PR-AUC against prevalence, LORO")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(plot_dir / "pr_auc_vs_prevalence.png", dpi=120)
    written.append("plots/pr_auc_vs_prevalence.png")
    plt.close(fig)

    part = reliability[(reliability["family"] == family)]
    targets = list(gv.REGIONS) + [gv.EXTERNAL_REGION]
    fig, axes = plt.subplots(2, 4, figsize=(14, 7), sharex=True, sharey=True)
    for ax, target in zip(axes.flat, targets):
        for method, rows in part[part["region"] == target].groupby("method"):
            ax.plot(rows["mean_probability"], rows["observed_rate"], marker="o", ms=3, label=method)
        ax.plot([0, 1], [0, 1], "k:", lw=0.8)
        ax.set_title(target, fontsize=9)
    axes.flat[-1].axis("off")
    axes.flat[0].legend(fontsize=7)
    fig.suptitle(f"Reliability, {family}: raw vs Platt vs isotonic (fit on validation rows only)")
    fig.tight_layout()
    fig.savefig(plot_dir / "reliability.png", dpi=120)
    written.append("plots/reliability.png")
    plt.close(fig)

    psi = shift.pivot_table(index="target", columns="feature", values="psi").reindex(targets)
    fig, ax = plt.subplots(figsize=(12, 4))
    image = ax.imshow(psi.to_numpy(), cmap="viridis", vmin=0, vmax=max(0.5, float(np.nanmax(psi.to_numpy()))))
    ax.set_xticks(range(psi.shape[1]), psi.columns, rotation=60, ha="right", fontsize=8)
    ax.set_yticks(range(psi.shape[0]), psi.index, fontsize=8)
    fig.colorbar(image, ax=ax, label="PSI (>0.25 large)")
    ax.set_title("Feature shift of each held-out region against its training rows")
    fig.tight_layout()
    fig.savefig(plot_dir / "shift_psi.png", dpi=120)
    written.append("plots/shift_psi.png")
    plt.close(fig)
    return written


# --- entry point -------------------------------------------------------------------------------

def run_diagnostics(train: pd.DataFrame, external: pd.DataFrame, loro: dict, external_results: dict,
                    family: str, out: Path, log=print) -> dict:
    feature_rows, region_rows = [], []
    for result in loro[family]["results"]:
        region = result["region"]
        reference = train.loc[result["_train_index"]]
        target = train[train["region"] == region]
        fitted = result["_fitted"]
        validation = {"index": fitted.validation_index, "labels": fitted.validation_labels,
                      "scores": fitted.validation_scores}
        feature_rows += feature_shift_rows(reference, target, region)
        region_rows.append(shift_vs_failure(reference, target, validation, result["_raw"], region))
        log(f"    shift {region:17s} domain AUC {region_rows[-1]['domain_auc']:.3f}: {region_rows[-1]['verdict']}")
    ext = external_results[family]
    fitted = ext["_fitted"]
    validation = {"index": fitted.validation_index, "labels": fitted.validation_labels,
                  "scores": fitted.validation_scores}
    feature_rows += feature_shift_rows(train, external, gv.EXTERNAL_REGION)
    region_rows.append(shift_vs_failure(train, external, validation, ext["_raw"], gv.EXTERNAL_REGION))
    log(f"    shift rainier           domain AUC {region_rows[-1]['domain_auc']:.3f}: {region_rows[-1]['verdict']}")
    summaries = pd.DataFrame(feature_rows).groupby("target").agg(
        mean_abs_smd=("smd", lambda s: float(np.nanmean(np.abs(s)))), max_psi=("psi", "max"),
        features_psi_over_0_25=("psi", lambda s: int((s > 0.25).sum())))
    for row in region_rows:
        row.update(summaries.loc[row["target"]].to_dict())

    tpi_scale = float(train["tpi_500"].std())
    pooled = loro[family]["pooled"]
    loro_frame = annotate(train, tpi_scale).assign(
        score=pooled["raw"].to_numpy(float), probability=pooled["isotonic"].to_numpy(float))
    loro_frame["outcome"] = outcome(loro_frame["label"].to_numpy(), loro_frame["score"].to_numpy(),
                                    pooled["threshold_max_f1"].to_numpy(float))
    ext_frame = annotate(external, tpi_scale).assign(score=ext["_raw"], probability=ext["_probs"]["isotonic"])
    ext_frame["outcome"] = outcome(ext_frame["label"].to_numpy(), ext_frame["score"].to_numpy(),
                                   np.full(len(ext_frame), fitted.thresholds["max_f1"]["threshold"]))
    bands, contrasts, clusters, fps, fns = [], [], [], [], []
    for scheme, frame in (("loro", loro_frame), ("external", ext_frame)):
        bands += band_rows(frame, scheme)
        contrasts += contrast_rows(frame, scheme)
        clusters += cluster_rows(frame, scheme)
        fp, fn = top_errors(frame, scheme)
        fps.append(fp)
        fns.append(fn)
    gv.write_csv(feature_rows, out / "shift_features.csv")
    gv.write_csv(region_rows, out / "shift_regions.csv")
    gv.write_csv(bands, out / "errors_by_band.csv")
    gv.write_csv(contrasts, out / "errors_feature_contrast.csv")
    gv.write_csv(clusters, out / "errors_spatial_clusters.csv")
    pd.concat(fps).to_csv(out / "top_false_positives.csv", index=False, float_format="%.5f")
    pd.concat(fns).to_csv(out / "top_false_negatives.csv", index=False, float_format="%.5f")

    per_region = pd.read_csv(out / "loro_per_region.csv")
    reliability = pd.read_csv(out / "reliability.csv")
    written = plots(out, train, loro, family, per_region, reliability, pd.DataFrame(feature_rows), log)
    return {"family": family, "regions": region_rows, "plots": written,
            "error_threshold_policy": "max-F1 threshold chosen on each fit's validation rows",
            "rainfall_errors": "terrain rows carry no rainfall; see combined_validate.py"}
