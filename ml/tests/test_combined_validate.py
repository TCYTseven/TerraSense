"""Tests for the combined terrain x rain validation design."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from affine import Affine

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "ml" / "scripts"))

import combined_validate as cv  # noqa: E402
from event_catalog import snap  # noqa: E402


def test_constants_match_live_model_b():
    source = (REPO_ROOT / "backend" / "app" / "ml" / "model_b.py").read_text()
    for name in ("W0", "W1", "W2", "W3", "SUSCEPTIBILITY_CLIP"):
        value = float(re.search(rf"^{name} = ([-0-9.e]+)", source, re.M).group(1))
        assert getattr(cv, name) == pytest.approx(value), name
    assert "TERRAIN_BASE_LOGIT = float(np.log(0.25 / 0.75))" in source
    assert cv.TERRAIN_BASE_LOGIT == pytest.approx(np.log(0.25 / 0.75))


def test_live_index_formula():
    assert cv.live_index(0.25, 0.0, 0.0) == pytest.approx(cv.sigmoid(cv.W0))
    s, r, m = 0.6, 0.3, -0.2
    expected = 1 / (1 + np.exp(-(np.log(0.6 / 0.4) - np.log(1 / 3) + cv.W0 + cv.W2 * r + cv.W3 * m)))
    assert cv.live_index(s, r, m) == pytest.approx(expected)
    assert np.isfinite(cv.live_index(np.array([0.0, 1.0]), 0.0, 0.0)).all()


def records_frame():
    return pd.DataFrame({
        "record_id": ["a1", "a2", "a3", "b1", "b2"],
        "cluster_id": ["A", "A", "A", "B", "B"],
        "source": ["nasa_glc", "usgs_v3", "usgs_v3", "nasa_glc", "nasa_glc"],
        "lon": [-122.0, -122.01, -122.02, -121.5, -121.51], "lat": [47.0, 47.01, 47.02, 46.9, 46.91],
    })


def test_case_records_prefer_precise_locations_and_are_deterministic():
    picks = cv.pick_case_records(records_frame(), draws=20)
    a = picks[picks["cluster_id"] == "A"]
    assert set(a["lon"]) <= {-122.01, -122.02} and a["precise"].all()
    b = picks[picks["cluster_id"] == "B"]
    assert not b["precise"].any() and len(b) == 20
    assert picks.equals(cv.pick_case_records(records_frame(), draws=20))


def design_rows():
    rain = {"rainfall_exceedance": 0.0, "past_72h_exceedance": 0.0, "moisture_index": 0.0, "next_72h_mm": 0.0,
            "past_72h_mm": 0.0, "past_7d_mm": 0.0}
    rows = []
    for cid, wy in (("A", 2000), ("B", 2005)):
        rows.append({"cluster_id": cid, "role": "case", "day": f"{wy}-01-10", "water_year": wy,
                     "sample_water_year": wy, "storm_id": f"s{cid}", "cell_id": cid, "inventories": "WA WGS",
                     **rain, "rainfall_exceedance": 0.9, "moisture_index": 0.8})
        for j, cy in enumerate((wy - 3, wy + 4)):
            rows.append({"cluster_id": cid, "role": "control", "day": f"{cy}-01-10", "water_year": wy,
                         "sample_water_year": cy, "storm_id": f"s{cid}", "cell_id": cid, "inventories": "WA WGS",
                         **rain, "rainfall_exceedance": -0.5 + j * 0.1})
    return pd.DataFrame(rows)


def design_points():
    pts = []
    for cid in ("A", "B"):
        pts.append({"cluster_id": cid, "point": "case_0", "s": 0.7, "precise": True, "region": "r", "lon": 0, "lat": 0})
        for j in range(3):
            pts.append({"cluster_id": cid, "point": f"place_{j}", "s": 0.1 * (j + 1), "precise": True,
                        "region": "r", "lon": j, "lat": j})
    return pd.DataFrame(pts)


def test_assemble_builds_the_full_two_by_two():
    rows = cv.assemble(design_points(), design_rows(), draw=0)
    counts = rows.groupby(["cluster_id", "kind"]).size().unstack()
    assert counts.loc["A"].to_dict() == {"case": 1, "same_place_other_day": 2, "other_place_same_day": 3,
                                        "other_place_other_day": 6}
    assert (rows["label"] == (rows["kind"] == "case")).all()
    case_rain = rows[rows["kind"] == "case"].set_index("cluster_id")["rainfall_exceedance"]
    same_day = rows[rows["kind"] == "other_place_same_day"]
    assert (same_day["rainfall_exceedance"].to_numpy() == same_day["cluster_id"].map(case_rain).to_numpy()).all()
    same_place = rows[rows["kind"] == "same_place_other_day"]
    assert (same_place["s"] == 0.7).all() and (same_place["sample_water_year"] != same_place["water_year"]).all()
    other = rows[rows["kind"] == "other_place_other_day"]
    assert set(other["rainfall_exceedance"]) == {-0.5, -0.4}


def test_fitted_combinations_never_train_on_held_out_years(monkeypatch):
    rng = np.random.default_rng(0)
    frames = []
    for i in range(40):
        wy = 1990 + i % 20
        frames.append(pd.DataFrame({
            "cluster_id": f"c{i}", "water_year": wy, "sample_water_year": [wy, wy - 5, wy + 5, wy],
            "label": [1, 0, 0, 0], "x1": rng.normal(size=4)}))
    rows = pd.concat(frames, ignore_index=True)
    seen = []
    original = cv.LogisticRegression.fit

    def recording(self, x, y):
        seen.append(len(y))
        return original(self, x, y)

    monkeypatch.setattr(cv.LogisticRegression, "fit", recording)
    sets = rows.drop_duplicates("cluster_id").set_index("cluster_id")[["water_year"]]
    fold_of_set = cv.ev.year_block_folds(sets)
    for fold in range(cv.ev.N_FOLDS):
        train, test = cv.ev.train_test_masks(rows, fold_of_set, fold, "year")
        held = set(rows.loc[test, "water_year"])
        assert not set(rows.loc[train, "sample_water_year"]) & held
        assert not set(rows.loc[train, "cluster_id"]) & set(rows.loc[test, "cluster_id"])
    out = cv.oof_logistic(rows, ["x1"])
    assert np.isfinite(out).all() and len(seen) == cv.ev.N_FOLDS


def test_concordance_by_kind():
    rows = pd.DataFrame({"cluster_id": ["A"] * 4, "kind": ["case", "same_place_other_day", "other_place_same_day",
                                                            "other_place_other_day"]})
    out = cv.concordance_by_kind(rows, np.array([0.5, 0.2, 0.5, 0.9]))
    assert out == {"same_place_other_day": 1.0, "other_place_same_day": 0.5, "other_place_other_day": 0.0}


def test_weather_cell_candidates_snap_to_the_cell():
    transform = Affine(30.0, 0.0, 540_000.0, 0.0, -30.0, 5_230_000.0)
    shape = (800, 800)
    stable = np.ones(shape, dtype=bool)
    lon, lat = cv.weather_cell_candidates(47.15, -122.45, transform, shape, stable)
    assert lon.size > 1000
    assert (snap(lat) == 47.15).all() and (snap(lon) == -122.45).all()
    none_lon, _ = cv.weather_cell_candidates(47.15, -122.45, transform, shape, np.zeros(shape, dtype=bool))
    assert none_lon.size == 0
