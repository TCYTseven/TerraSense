"""Feature-group ablation and transfer analysis for the regional susceptibility model.

Called by `geo_validate.py` (skip with `--skip-ablation`). Every variant is trained with fixed
hyperparameters (the deployed LightGBM params and a C=1 logistic) and scored two ways: the deployed
10 km block spatial CV, and leave-one-region-out (LORO). Only raw-score ranking is compared (ROC-AUC,
PR-AUC, lift), since calibration does not change which features carry signal.

A group is "non-transferable" when removing it lowers spatial-CV ROC-AUC (it helps inside the
training distribution) but raises mean LORO ROC-AUC (it hurts unseen regions). The minimal
transferable set keeps the slope group plus every group whose removal costs at least
MIN_LORO_GAIN of mean LORO ROC-AUC and that hurts fewer than HARM_REGIONS regions.

Rainier is scored only for the final minimal set, once, and never feeds back into the choice.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import geo_metrics as gm
import geo_validate as gv
import train_regional_susceptibility as trs

FEATURE_GROUPS = {
    "slope": ("slope", "slope_std_150"),
    "aspect": ("aspect_sin", "aspect_cos"),
    "curvature": ("curvature", "profile_curvature", "plan_curvature"),
    "relief": ("relief_150", "relief_500", "relief_1000", "roughness_90"),
    "position": ("tpi_500", "tpi_1000"),
    "hydrology": ("dist_drainage", "twi"),  # distance to drainage stands in for distance to streams
    "landcover": ("landcover",),
}
# Requested groups with no regional layer in data/raw. They are reported, never approximated.
UNAVAILABLE_GROUPS = {
    "geology": "no geologic map is downloaded for the region",
    "soil": "SoilGrids rasters in data/raw/soilgrids cover only the Rainier box, so no training row has them",
    "precipitation_climatology": "no rainfall normals (PRISM or similar) are downloaded; the Open-Meteo "
                                 "archive holds only event and control windows",
    "distance_to_roads": "data/raw/osm/washington-latest.osm.pbf exists but is not rasterized to the grid "
                         "and no OSM reader is installed",
}
ABLATION_MODELS = {
    "lgbm": gv.Family("lgbm", "lgbm", (), ({"num_leaves": 7, "min_child_samples": 200},), 5),
    "logistic": gv.Family("logistic", "logistic", (), ({"C": 1.0},), 2),
}
MIN_LORO_GAIN = 0.005
HARM_REGIONS = 4  # of the six held-out regions


def variants() -> dict[str, tuple[str, ...]]:
    full = gv.MODEL_FEATURES
    out = {"slope_only": ("slope",), "slope_group": FEATURE_GROUPS["slope"], "full": full}
    for group, members in FEATURE_GROUPS.items():
        out[f"minus_{group}"] = tuple(f for f in full if f not in members)
    out["plus_elevation"] = full + ("elevation",)
    return out


def with_features(model: gv.Family, features: tuple[str, ...]) -> gv.Family:
    return gv.Family(model.name, model.kind, tuple(features), model.grid, model.complexity)


def score_variant(train: pd.DataFrame, family: gv.Family) -> list[dict]:
    """Raw-score ranking metrics per LORO region and per spatial-CV fold, fixed params."""
    params = family.grid[0]
    rows = []
    xy, regions = gv.xy_of(train), train["region"].to_numpy()
    for region in gv.REGIONS:
        tr, te = gv.buffered_split(xy, regions, region)
        raw = gv.Scorer(family, params, train[tr]).score(train[te])
        rows.append({"scheme": "loro", "split": region, **gm.ranking_metrics(train["label"].to_numpy()[te], raw)})
    x, y, labels = train["x"].to_numpy(), train["y"].to_numpy(), train["label"].to_numpy()
    blocks = trs.block_ids(x, y)
    folds = trs.assign_folds(blocks, labels)
    for k in range(trs.N_FOLDS):
        tr, te = trs.split_with_buffer(x, y, blocks, folds, k)
        raw = gv.Scorer(family, params, train[tr]).score(train[te])
        rows.append({"scheme": "spatial_cv", "split": f"fold_{k}", **gm.ranking_metrics(labels[te], raw)})
    return rows


def transfer_table(per_split: pd.DataFrame, model: str) -> list[dict]:
    """Per group: what removing it does to spatial CV and to unseen regions."""
    part = per_split[per_split["model"] == model]
    wide = part.pivot_table(index=["scheme", "split"], columns="variant", values="roc_auc")
    wide_pr = part.pivot_table(index=["scheme", "split"], columns="variant", values="pr_auc")
    rows = []
    for group in FEATURE_GROUPS:
        minus = f"minus_{group}"
        cv, loro = wide.loc["spatial_cv"], wide.loc["loro"]
        cv_delta = float((cv["full"] - cv[minus]).mean())
        loro_delta = float((loro["full"] - loro[minus]).mean())
        regions_hurt = int((loro[minus] > loro["full"]).sum())
        rows.append({
            "model": model, "group": group, "features": ",".join(FEATURE_GROUPS[group]),
            "cv_roc_gain": cv_delta, "loro_roc_gain": loro_delta,
            "cv_pr_gain": float((wide_pr.loc["spatial_cv"]["full"] - wide_pr.loc["spatial_cv"][minus]).mean()),
            "loro_pr_gain": float((wide_pr.loc["loro"]["full"] - wide_pr.loc["loro"][minus]).mean()),
            "regions_where_removal_helps": regions_hurt,
            "improves_cv_hurts_external": bool(cv_delta > 0 and loro_delta < 0),
            "consistently_harms_external": bool(regions_hurt >= HARM_REGIONS),
        })
    harmful = sorted((r for r in rows if r["loro_roc_gain"] < 0), key=lambda r: r["loro_roc_gain"])
    for rank, row in enumerate(harmful, start=1):
        row["non_transferable_rank"] = rank
    return rows


def minimal_set(transfer: list[dict]) -> tuple[str, ...]:
    keep = ["slope"] + [r["group"] for r in transfer
                        if r["group"] != "slope" and r["loro_roc_gain"] >= MIN_LORO_GAIN
                        and r["regions_where_removal_helps"] < HARM_REGIONS]
    return tuple(f for g in keep for f in FEATURE_GROUPS[g])


def run_ablation(train: pd.DataFrame, external: pd.DataFrame, log=print) -> dict:
    per_split = []
    for model_name, model in ABLATION_MODELS.items():
        for variant, features in variants().items():
            for row in score_variant(train, with_features(model, features)):
                per_split.append({"model": model_name, "variant": variant, **row})
            log(f"    ablation {model_name:8s} {variant:18s} done")
    frame = pd.DataFrame(per_split)
    transfer, minimal = [], {}
    for model_name, model in ABLATION_MODELS.items():
        rows = transfer_table(frame, model_name)
        transfer += rows
        features = minimal_set(rows)
        minimal[model_name] = features
        family = with_features(model, features)
        for row in score_variant(train, family):
            per_split.append({"model": model_name, "variant": "minimal_transferable", **row})
    frame = pd.DataFrame(per_split)
    summary = []
    for (model_name, variant, scheme), group in frame.groupby(["model", "variant", "scheme"], sort=False):
        summary.append({"model": model_name, "variant": variant, "scheme": scheme,
                        **{f"{m}_{s}": v for m in ("roc_auc", "pr_auc", "lift")
                           for s, v in gm.summarize(group[m]).items() if s in ("mean", "median", "std", "min")}})
    # One look at Rainier for the minimal sets and the full set they are compared with.
    external_rows = []
    for model_name, model in ABLATION_MODELS.items():
        for variant, features in (("full", gv.MODEL_FEATURES), ("minimal_transferable", minimal[model_name])):
            family = with_features(model, features)
            raw = gv.Scorer(family, family.grid[0], train).score(external)
            external_rows.append({"model": model_name, "variant": variant, "features": ",".join(features),
                                  **gm.ranking_metrics(external["label"].to_numpy(), raw)})
    return {"per_split": per_split, "summary": summary, "transfer": transfer,
            "minimal_features": {k: list(v) for k, v in minimal.items()}, "external": external_rows,
            "unavailable_groups": UNAVAILABLE_GROUPS, "groups": {k: list(v) for k, v in FEATURE_GROUPS.items()},
            "rule": {"min_loro_gain": MIN_LORO_GAIN, "harm_regions": HARM_REGIONS}}
