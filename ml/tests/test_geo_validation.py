"""Tests for the leave-one-region-out geographic validation and its metrics."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pyproj import Transformer
from sklearn.metrics import average_precision_score, roc_auc_score

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "ml" / "scripts"))

import geo_ablation as ga  # noqa: E402
import geo_diagnostics as gd  # noqa: E402
import geo_metrics as gm  # noqa: E402
import geo_validate as gv  # noqa: E402
import train_regional_susceptibility as trs  # noqa: E402

CHEAP_FAMILIES = "random,slope_only,logistic,lgbm_stumps"


# --- metrics -----------------------------------------------------------------------------------

def test_ranking_metrics_prevalence_and_lift():
    labels = np.array([0, 0, 0, 1, 1, 0, 1, 0])
    scores = np.array([0.1, 0.4, 0.35, 0.8, 0.7, 0.2, 0.3, 0.05])
    m = gm.ranking_metrics(labels, scores)
    assert m["prevalence"] == pytest.approx(3 / 8)
    assert m["roc_auc"] == pytest.approx(roc_auc_score(labels, scores))
    assert m["pr_auc"] == pytest.approx(average_precision_score(labels, scores))
    assert m["lift"] == pytest.approx(m["pr_auc"] / (3 / 8))


def test_ranking_metrics_single_class_is_nan():
    m = gm.ranking_metrics(np.zeros(5), np.linspace(0, 1, 5))
    assert np.isnan(m["roc_auc"]) and np.isnan(m["pr_auc"]) and np.isnan(m["lift"])
    assert m["prevalence"] == 0.0


def test_random_scores_have_lift_near_one():
    rng = np.random.default_rng(0)
    labels = (rng.random(20_000) < 0.1).astype(int)
    m = gm.ranking_metrics(labels, rng.random(labels.size))
    assert m["roc_auc"] == pytest.approx(0.5, abs=0.02)
    assert m["lift"] == pytest.approx(1.0, abs=0.1)


def test_confusion_counts():
    labels = np.array([1, 1, 0, 0, 1, 0])
    scores = np.array([0.9, 0.2, 0.8, 0.1, 0.6, 0.4])
    c = gm.confusion(labels, scores, 0.5)
    assert (c["tp"], c["fp"], c["tn"], c["fn"]) == (2, 1, 2, 1)
    assert c["precision"] == pytest.approx(2 / 3)
    assert c["recall"] == pytest.approx(2 / 3)
    assert c["f1"] == pytest.approx(2 / 3)
    assert c["specificity"] == pytest.approx(2 / 3)
    assert c["share_flagged"] == pytest.approx(0.5)


def test_ece_matches_the_deployed_trainer():
    rng = np.random.default_rng(1)
    probs = rng.random(500)
    labels = (rng.random(500) < probs ** 2).astype(int)
    assert gm.expected_calibration_error(labels, probs) == pytest.approx(
        trs.expected_calibration_error(labels, probs))


def test_summarize_ignores_nan():
    s = gm.summarize([0.5, 0.7, float("nan"), 0.9])
    assert s == {"mean": pytest.approx(0.7), "median": pytest.approx(0.7), "std": pytest.approx(0.2),
                 "min": 0.5, "max": 0.9, "n": 3}


def test_precision_at_prevalence():
    assert gm.precision_at_prevalence(0.5, 0.1, 0.25) == pytest.approx(0.125 / (0.125 + 0.075))


def brute_thresholds(labels, scores):
    rows = []
    for t in np.unique(scores):
        c = gm.confusion(labels, scores, t)
        rows.append((t, c["precision"], c["recall"], c["f1"]))
    return pd.DataFrame(rows, columns=["t", "p", "r", "f1"])


def test_select_thresholds_matches_brute_force():
    rng = np.random.default_rng(2)
    labels = (rng.random(400) < 0.3).astype(int)
    scores = np.clip(0.3 * labels + rng.random(400) * 0.7, 0, 1)
    chosen = gm.select_thresholds(labels, scores)
    brute = brute_thresholds(labels, scores)
    best = gm.confusion(labels, scores, chosen["max_f1"]["threshold"])["f1"]
    assert best == pytest.approx(brute["f1"].max())
    for target in gm.PRECISION_TARGETS:
        pick = chosen[f"precision_{target:.2f}"]
        ok = brute[brute["p"] >= target]
        if ok.empty:
            assert not pick["reachable"]
            continue
        assert pick["val_precision"] >= target
        assert pick["val_recall"] == pytest.approx(ok["r"].max())
    for target in gm.RECALL_TARGETS:
        pick = chosen[f"recall_{target:.2f}"]
        ok = brute[brute["r"] >= target]
        assert pick["val_recall"] >= target
        assert pick["threshold"] == pytest.approx(ok["t"].max())


def test_unreachable_precision_target_is_not_evaluated():
    labels = np.array([0, 1, 0, 1, 0, 1])
    scores = np.full(6, 0.5)  # one tied score: precision is 0.5 at every threshold
    chosen = gm.select_thresholds(labels, scores)
    assert not chosen["precision_0.80"]["reachable"]
    rows = gm.apply_thresholds(labels, scores, chosen)
    row = next(r for r in rows if r["policy"] == "precision_0.80")
    assert np.isnan(row["threshold"]) and "tp" not in row


def test_apply_thresholds_uses_the_validation_threshold_unchanged():
    rng = np.random.default_rng(3)
    val_labels = (rng.random(300) < 0.25).astype(int)
    val_scores = np.clip(0.4 * val_labels + rng.random(300) * 0.6, 0, 1)
    chosen = gm.select_thresholds(val_labels, val_scores)
    test_labels = 1 - (rng.random(200) < 0.75).astype(int)
    test_scores = rng.random(200)
    for row in gm.apply_thresholds(test_labels, test_scores, chosen):
        if row["reachable_on_validation"]:
            assert row["threshold"] == chosen[row["policy"]]["threshold"]


def test_calibrators():
    rng = np.random.default_rng(4)
    scores = rng.random(2000)
    labels = (rng.random(2000) < scores ** 3).astype(int)
    with pytest.raises(RuntimeError):
        gm.Calibrator("platt").predict(scores)
    with pytest.raises(ValueError):
        gm.Calibrator("beta")
    platt = gm.Calibrator("platt").fit(scores, labels)
    iso = gm.Calibrator("isotonic").fit(scores, labels)
    assert platt.fitted_on == 2000
    assert roc_auc_score(labels, platt.predict(scores)) == pytest.approx(roc_auc_score(labels, scores))
    assert gm.expected_calibration_error(labels, iso.predict(scores)) < gm.expected_calibration_error(labels, scores)
    assert np.array_equal(gm.Calibrator("raw").fit(scores, labels).predict(scores), scores)


def test_shift_statistics():
    rng = np.random.default_rng(5)
    a = rng.normal(0, 1, 5000)
    same = gm.shift_statistics(a, a)
    assert same["smd"] == pytest.approx(0) and same["ks"] == pytest.approx(0)
    assert same["psi"] == pytest.approx(0, abs=1e-9) and same["wasserstein_std"] == pytest.approx(0)
    moved = gm.shift_statistics(a, rng.normal(1, 1, 5000))
    assert moved["smd"] == pytest.approx(1, abs=0.1)
    assert moved["psi"] > 0.25 and moved["ks"] > 0.3
    assert moved["wasserstein_std"] == pytest.approx(1, abs=0.1)
    cat = gm.shift_statistics(np.array([10, 10, 20, 30]), np.array([10, 20, 20, 20]), categorical=True)
    assert cat["total_variation"] == pytest.approx(0.5) and np.isnan(cat["smd"])


# --- regions and splits ------------------------------------------------------------------------

def test_region_of_corners():
    lon = np.array([-122.5, -121.3, -122.5, -121.3, -122.5, -121.3])
    lat = np.array([46.5, 46.5, 47.0, 47.0, 47.4, 47.4])
    assert gv.region_of(lon, lat).tolist() == list(gv.REGIONS)
    assert gv.region_of([gv.REGION_LON_SPLIT], [gv.REGION_LAT_SPLITS[0]])[0] == "central_cascades"


def synthetic_table(n_per_region: int = 260, seed: int = 0) -> pd.DataFrame:
    """Rows spread over the six regions plus a Rainier external set, with signal in slope."""
    rng = np.random.default_rng(seed)
    lon_edges = (-122.55, gv.REGION_LON_SPLIT, -121.25)
    lat_edges = (46.45, *gv.REGION_LAT_SPLITS, 47.45)
    parts = []
    for i in range(3):
        for j in range(2):
            lon = rng.uniform(lon_edges[j] + 0.02, lon_edges[j + 1] - 0.02, n_per_region)
            lat = rng.uniform(lat_edges[i] + 0.02, lat_edges[i + 1] - 0.02, n_per_region)
            keep = ~((lon > -121.97) & (lon < -121.50) & (lat > 46.74) & (lat < 46.98))
            parts.append(pd.DataFrame({"lon": lon[keep], "lat": lat[keep], "set": "train"}))
    ext = pd.DataFrame({"lon": rng.uniform(-121.9, -121.56, 120), "lat": rng.uniform(46.77, 46.95, 120),
                        "set": "external"})
    frame = pd.concat(parts + [ext], ignore_index=True)
    x, y = Transformer.from_crs("EPSG:4326", gv.GRID_CRS, always_xy=True).transform(frame["lon"], frame["lat"])
    frame["x"], frame["y"] = np.round(np.asarray(x) / 30) * 30 + 15, np.round(np.asarray(y) / 30) * 30 + 15
    n = len(frame)
    signal = rng.normal(0, 1, n)
    frame["label"] = (signal + rng.normal(0, 1, n) > 0.9).astype("int8")
    for name in trs.STACK_FEATURES:
        frame[name] = rng.normal(0, 1, n).astype("float32")
    frame["slope"] = (20 + 8 * signal).astype("float32")
    frame["landcover"] = rng.choice([10, 20, 30, 60], n).astype("float32")
    frame["source"] = np.where(frame["label"] == 1, "WA WGS", "negative")
    frame["confidence"] = np.where(frame["label"] == 1, 5.0, np.nan)
    frame["dist_any_record_m"] = np.where(frame["label"] == 1, 0.0, rng.uniform(500, 3000, n)).astype("float32")
    return frame.drop(columns=["lon", "lat"])


@pytest.fixture(scope="module")
def table():
    return gv.with_regions(synthetic_table())


def test_with_regions_marks_external(table):
    assert set(table.loc[table["set"] == "external", "region"]) == {gv.EXTERNAL_REGION}
    assert set(table.loc[table["set"] == "train", "region"]) == set(gv.REGIONS)


def test_buffered_split_has_no_region_leak(table):
    train = table[table["set"] == "train"]
    xy, regions = gv.xy_of(train), train["region"].to_numpy()
    for region in gv.REGIONS:
        tr, te = gv.buffered_split(xy, regions, region)
        assert not (tr & te).any()
        assert set(regions[te]) == {region} and region not in set(regions[tr])
        brute = np.sqrt(((xy[tr][:, None, :] - xy[te][None, :, :]) ** 2).sum(-1)).min()
        assert brute > gv.CV_BUFFER_M
        assert gv.min_distance(xy[tr], xy[te]) == pytest.approx(brute)


def test_coordinate_uniform_is_deterministic_and_uniform():
    rng = np.random.default_rng(6)
    x, y = rng.uniform(5e5, 6e5, 20_000), rng.uniform(5.1e6, 5.2e6, 20_000)
    a, b = gv.coordinate_uniform(x, y), gv.coordinate_uniform(x, y)
    assert np.array_equal(a, b) and a.min() >= 0 and a.max() < 1
    assert a.mean() == pytest.approx(0.5, abs=0.01)


# --- validation-only fitting -------------------------------------------------------------------

def test_calibrators_and_thresholds_see_only_validation_rows(table, monkeypatch):
    train = table[table["set"] == "train"]
    seen = []
    original = gm.select_thresholds

    def recording(labels, scores, *args, **kwargs):
        seen.append(len(labels))
        return original(labels, scores, *args, **kwargs)

    monkeypatch.setattr(gm, "select_thresholds", recording)
    xy, regions = gv.xy_of(train), train["region"].to_numpy()
    tr, te = gv.buffered_split(xy, regions, "north_lowland")
    fitted = gv.fit_with_validation(train[tr], gv.FAMILY_BY_NAME["logistic"], log=lambda *_: None)
    held_out = set(train.index[te])
    assert held_out.isdisjoint(fitted.validation_index)
    assert set(fitted.validation_index) <= set(train.index[tr])
    assert seen == [len(fitted.validation_index)]
    assert all(c.fitted_on == len(fitted.validation_index) for c in fitted.calibrators.values())
    result = gv.evaluate_holdout(fitted, train[te], "north_lowland")
    assert result["ranking"]["n"] == int(te.sum())


def test_evaluate_holdout_refuses_rows_used_for_validation(table):
    train = table[table["set"] == "train"]
    fitted = gv.fit_with_validation(train, gv.FAMILY_BY_NAME["slope_only"], log=lambda *_: None)
    with pytest.raises(AssertionError):
        gv.evaluate_holdout(fitted, train.iloc[:50], "leak")


def test_inner_validation_never_sees_the_outer_region(table, monkeypatch):
    train = table[table["set"] == "train"]
    fits = []
    original = gv.Scorer.__init__

    def recording(self, family, params, frame):
        fits.append(set(frame["region"]))
        original(self, family, params, frame)

    monkeypatch.setattr(gv.Scorer, "__init__", recording)
    gv.run_loro(train, gv.FAMILY_BY_NAME["logistic"], log=lambda *_: None)
    # 6 outer regions x (5 inner regions x 3 params + 1 refit), none trained on its outer region.
    assert len(fits) == 6 * (5 * 3 + 1)
    per_outer = [fits[i * 16:(i + 1) * 16] for i in range(6)]
    for region, group in zip(gv.REGIONS, per_outer):
        assert all(region not in regions for regions in group)


def test_select_family_prefers_the_simplest_competitive_model():
    rows = []
    for family, pr, roc in (("random", 0.25, 0.5), ("slope_only", 0.40, 0.70), ("logistic", 0.495, 0.795),
                            ("lgbm_current", 0.50, 0.80)):
        rows += [{"scheme": "loro", "family": family, "metric": "pr_auc", "mean": pr},
                 {"scheme": "loro", "family": family, "metric": "roc_auc", "mean": roc}]
    chosen = gv.select_family(rows)
    assert chosen["family"] == "logistic"
    assert chosen["eligible"] == ["logistic", "lgbm_current"]


def test_paired_bootstrap_of_identical_scores_is_zero():
    rng = np.random.default_rng(7)
    x, y = rng.uniform(0, 20_000, 300), rng.uniform(0, 20_000, 300)
    labels = (rng.random(300) < 0.25).astype(int)
    scores = rng.random(300)
    out = gv.paired_bootstrap(labels, scores, scores, x, y, reps=50)
    assert out["roc_auc_diff"] == 0 and out["roc_auc_diff_ci95"] == [0.0, 0.0]
    better = gv.paired_bootstrap(labels, scores + labels, scores, x, y, reps=50)
    assert better["roc_auc_diff"] > 0 and better["roc_auc_diff_ci95"][0] > 0


# --- ablation ----------------------------------------------------------------------------------

def test_ablation_variants_remove_exactly_one_group():
    v = ga.variants()
    assert v["full"] == gv.MODEL_FEATURES and v["slope_only"] == ("slope",)
    assert "elevation" in v["plus_elevation"] and "elevation" not in v["full"]
    for group, members in ga.FEATURE_GROUPS.items():
        assert set(v["full"]) - set(v[f"minus_{group}"]) == set(members)
    grouped = [f for members in ga.FEATURE_GROUPS.values() for f in members]
    assert sorted(grouped) == sorted(gv.MODEL_FEATURES)
    assert set(ga.UNAVAILABLE_GROUPS) == {"geology", "soil", "precipitation_climatology", "distance_to_roads"}


def fake_split_frame(cv_minus: dict[str, float], loro_minus: dict[str, list[float]]) -> pd.DataFrame:
    rows = []
    for k in range(trs.N_FOLDS):
        rows.append({"model": "m", "variant": "full", "scheme": "spatial_cv", "split": f"fold_{k}",
                     "roc_auc": 0.80, "pr_auc": 0.5})
        for group in ga.FEATURE_GROUPS:
            rows.append({"model": "m", "variant": f"minus_{group}", "scheme": "spatial_cv", "split": f"fold_{k}",
                         "roc_auc": cv_minus.get(group, 0.80), "pr_auc": 0.5})
    for i, region in enumerate(gv.REGIONS):
        rows.append({"model": "m", "variant": "full", "scheme": "loro", "split": region,
                     "roc_auc": 0.70, "pr_auc": 0.4})
        for group in ga.FEATURE_GROUPS:
            rows.append({"model": "m", "variant": f"minus_{group}", "scheme": "loro", "split": region,
                         "roc_auc": loro_minus.get(group, [0.70] * 6)[i], "pr_auc": 0.4})
    return pd.DataFrame(rows)


def test_transfer_flags_features_that_help_cv_but_hurt_new_regions():
    frame = fake_split_frame(
        cv_minus={"aspect": 0.78, "relief": 0.75, "landcover": 0.79},
        loro_minus={"aspect": [0.72] * 6, "relief": [0.66] * 6, "landcover": [0.73, 0.73, 0.695, 0.695, 0.695, 0.695]})
    rows = {r["group"]: r for r in ga.transfer_table(frame, "m")}
    assert rows["aspect"]["improves_cv_hurts_external"] and rows["aspect"]["consistently_harms_external"]
    assert rows["aspect"]["regions_where_removal_helps"] == 6
    assert rows["aspect"]["loro_roc_gain"] == pytest.approx(-0.02)
    assert not rows["relief"]["improves_cv_hurts_external"]
    assert rows["landcover"]["improves_cv_hurts_external"] and not rows["landcover"]["consistently_harms_external"]
    assert rows["aspect"]["non_transferable_rank"] == 1 and rows["landcover"]["non_transferable_rank"] == 2
    assert "non_transferable_rank" not in rows["relief"]
    minimal = ga.minimal_set(list(rows.values()))
    assert set(minimal) == set(ga.FEATURE_GROUPS["slope"]) | set(ga.FEATURE_GROUPS["relief"])


# --- diagnostics -------------------------------------------------------------------------------

def test_feature_shift_rows_measure_extrapolation(table):
    train = table[table["set"] == "train"]
    same = {r["feature"]: r for r in gd.feature_shift_rows(train, train, "self")}
    assert same["slope"]["smd"] == pytest.approx(0) and same["slope"]["outside_reference_p1_p99"] <= 0.03
    moved = train.assign(slope=train["slope"] + 10 * train["slope"].std())
    rows = {r["feature"]: r for r in gd.feature_shift_rows(train, moved, "moved")}
    assert rows["slope"]["outside_reference_p1_p99"] > 0.95 and rows["slope"]["psi"] > 1
    assert np.isnan(rows["landcover"]["smd"]) and rows["landcover"]["total_variation"] == pytest.approx(0)


def test_domain_classifier_sees_shift_only_when_it_exists(table):
    train = table[table["set"] == "train"]
    a, b = train[train["region"].isin(gv.REGIONS[:3])], train[train["region"].isin(gv.REGIONS[3:])]
    _, _, auc_same = gd.domain_scores(a, b)
    _, _, auc_moved = gd.domain_scores(a, b.assign(relief_500=b["relief_500"] + 5))
    assert auc_same < 0.65 and auc_moved > 0.95


def test_outcome_labels():
    labels = np.array([1, 0, 0, 1])
    scores = np.array([0.9, 0.9, 0.1, 0.1])
    assert gd.outcome(labels, scores, np.full(4, 0.5)).tolist() == ["TP", "FP", "TN", "FN"]


def test_error_tables(table):
    frame = gd.annotate(table[table["set"] == "train"], 1.0)
    rng = np.random.default_rng(8)
    frame = frame.assign(score=rng.random(len(frame)), probability=rng.random(len(frame)))
    frame["outcome"] = gd.outcome(frame["label"].to_numpy(), frame["score"].to_numpy(), np.full(len(frame), 0.5))
    bands = pd.DataFrame(gd.band_rows(frame, "loro"))
    for grouping, part in bands.groupby("grouping"):
        assert part[["tp", "fp", "tn", "fn"]].to_numpy().sum() == len(frame), grouping
    fp, fn = gd.top_errors(frame, "loro")
    assert (fp["label"] == 0).all() and fp["score"].is_monotonic_decreasing
    assert (fn["label"] == 1).all() and fn["score"].is_monotonic_increasing
    assert {"lon", "lat", "region"} <= set(fp.columns) and len(fp) == gd.TOP_ERRORS


# --- end to end --------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    path = tmp_path_factory.mktemp("geo") / "table.parquet"
    synthetic_table().to_parquet(path)
    outs = []
    for name in ("a", "b"):
        out = tmp_path_factory.mktemp(name)
        assert gv.main(["--table", str(path), "--out", str(out), "--families", CHEAP_FAMILIES,
                        "--bootstrap", "50"]) == 0
        outs.append(out)
    return outs


def test_outputs_and_schema(runs):
    out = runs[0]
    per_region = pd.read_csv(out / "loro_per_region.csv")
    required = {"family", "region", "n", "positives", "prevalence", "roc_auc", "pr_auc", "lift", "precision",
                "recall", "f1", "tp", "fp", "tn", "fn", "ece_isotonic", "brier_isotonic"}
    assert required <= set(per_region.columns)
    assert set(per_region["region"]) == set(gv.REGIONS)
    assert set(per_region["family"]) == set(CHEAP_FAMILIES.split(","))
    summary = pd.read_csv(out / "summary.csv")
    assert {"scheme", "family", "metric", *gm.SUMMARY_STATS} <= set(summary.columns)
    assert set(summary["scheme"]) == {"loro", "spatial_cv"}
    ext = pd.read_csv(out / "rainier_external.csv")
    assert set(ext["region"]) == {gv.EXTERNAL_REGION}
    prevalence = pd.read_csv(out / "prevalence.csv")
    assert "external:rainier" in set(prevalence["split"])
    assert np.allclose(prevalence["prevalence"], prevalence["positives"] / prevalence["n"], atol=1e-4)
    thresholds = pd.read_csv(out / "thresholds.csv")
    assert {"max_f1", "precision_0.70", "recall_0.60"} <= set(thresholds["policy"])
    calibration = pd.read_csv(out / "calibration.csv")
    assert set(calibration["method"]) == set(gm.Calibrator.METHODS)
    report = (out / "report.json").read_text()
    assert "NaN" not in report and '"selection"' in report
    transfer = pd.read_csv(out / "ablation_transfer.csv")
    assert {"model", "group", "cv_roc_gain", "loro_roc_gain", "improves_cv_hurts_external",
            "consistently_harms_external", "regions_where_removal_helps"} <= set(transfer.columns)
    assert set(transfer["group"]) == set(ga.FEATURE_GROUPS)
    ablation = pd.read_csv(out / "ablation_summary.csv")
    assert {"slope_only", "full", "plus_elevation", "minimal_transferable"} <= set(ablation["variant"])
    assert set(ablation["scheme"]) == {"loro", "spatial_cv"}
    assert set(pd.read_csv(out / "ablation_rainier.csv")["variant"]) == {"full", "minimal_transferable"}
    shift = pd.read_csv(out / "shift_regions.csv")
    assert set(shift["target"]) == set(gv.REGIONS) | {gv.EXTERNAL_REGION}
    assert {"domain_auc", "shift_weighted_validation_roc_auc", "heldout_roc_auc", "verdict", "mean_abs_smd",
            "max_psi"} <= set(shift.columns)
    features = pd.read_csv(out / "shift_features.csv")
    assert {"smd", "psi", "ks", "wasserstein_std"} <= set(features.columns)
    for name in ("errors_by_band.csv", "errors_feature_contrast.csv", "errors_spatial_clusters.csv",
                 "top_false_positives.csv", "top_false_negatives.csv"):
        assert (out / name).exists(), name


def test_lift_column_is_pr_auc_over_prevalence(runs):
    per_region = pd.read_csv(runs[0] / "loro_per_region.csv")
    assert np.allclose(per_region["lift"], per_region["pr_auc"] / per_region["prevalence"], atol=2e-3)


def test_runs_are_deterministic(runs):
    for name in ("loro_per_region.csv", "summary.csv", "rainier_external.csv", "thresholds.csv",
                 "calibration.csv", "ablation_per_split.csv", "ablation_transfer.csv", "shift_regions.csv",
                 "errors_by_band.csv", "top_false_positives.csv"):
        assert (runs[0] / name).read_bytes() == (runs[1] / name).read_bytes(), name
