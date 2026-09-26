"""The live regional-model seam: real pixel parity with the baked map, and the stand-in path.

The parity test is the sync check for the whole feature: the backend's live prediction at a
stack pixel must equal the value apply_susceptibility_map.py baked into susceptibility.tif,
so the agents and the catalog quote the same model the heat map draws.
"""

import json

import numpy as np
import pytest
import rasterio

from app.ml import geo_susceptibility as geo
from app.risk import BIN_EDGES

pytestmark = pytest.mark.skipif(
    geo._artifacts_stamp() is None or not geo.STACK_PATH.is_file(),
    reason="model artifacts not built (susceptibility_lgbm.txt, calibration, regional stack)",
)

RAINIER_PEAK = (46.8523, -121.7603)
EVEREST_PEAK = (27.988, 86.925)

SUSCEPTIBILITY_TIF = geo.REPO_ROOT / "ml" / "artifacts" / "susceptibility.tif"


def test_rainier_summit_scores_its_own_pixel():
    result = geo.predict_summit("mount-rainier", *RAINIER_PEAK)
    assert result["available"] is True
    assert result["input_source"] == geo.REAL_INPUT
    assert 0.0 <= result["probability"] <= 1.0
    assert result["risk_level"] in ("low", "moderate", "high", "extreme")
    assert len(result["features"]) == 16
    assert result["drivers"] and result["drivers"][0]["importance"] > 0
    json.dumps(result)  # every payload that leaves the process must be JSON-native


def test_prediction_matches_the_baked_map():
    """The live seam and the offline map are the same model on the same features."""
    if not SUSCEPTIBILITY_TIF.is_file():
        pytest.skip("susceptibility.tif not baked")
    with rasterio.open(SUSCEPTIBILITY_TIF) as src:
        values = src.read(1)
        rows, cols = np.where(np.isfinite(values))
        picks = np.random.default_rng(26).choice(len(rows), 5, replace=False)
        points = []
        for i in picks:
            x, y = src.xy(rows[i], cols[i])
            points.append((float(values[rows[i], cols[i]]), x, y, src.crs))
    from rasterio.warp import transform as warp_transform

    for expected, x, y, crs in points:
        lon, lat = (c[0] for c in warp_transform(crs, "EPSG:4326", [x], [y]))
        result = geo.predict_summit(f"parity-{x:.0f}-{y:.0f}", lat, lon)
        assert result["input_source"] == geo.REAL_INPUT
        assert result["probability"] == pytest.approx(expected, abs=2e-4)


def test_placeholder_is_deterministic_and_labeled():
    first = geo.predict_summit("mount-everest", *EVEREST_PEAK)
    again = geo.predict_summit("mount-everest", *EVEREST_PEAK)
    assert first["input_source"] == geo.PLACEHOLDER_INPUT
    assert "stand-in" .replace(" ", "-") in first["note"].lower() or "stand-in" in first["note"].lower()
    assert first["probability"] == again["probability"]
    assert 0.0 <= first["probability"] <= 1.0
    assert first["features"]["landcover"] != geo.WATER_CLASS


def test_placeholder_varies_by_slug():
    slugs = ["mount-everest", "kilimanjaro", "denali", "aconcagua", "mont-blanc"]
    values = {geo.predict_summit(slug, *EVEREST_PEAK)["probability"] for slug in slugs}
    assert len(values) > 1  # different slugs sample different ground


def test_risk_level_matches_shared_bins():
    result = geo.predict_summit("mount-everest", *EVEREST_PEAK)
    p = result["probability"]
    low, high_edge, extreme = BIN_EDGES
    expected = "low" if p < low else "moderate" if p < high_edge else "high" if p < extreme else "extreme"
    assert result["risk_level"] == expected


def test_polar_summit_uses_placeholder_not_projection_error():
    """Antarctic peaks are outside the Rainier UTM stack's warp domain; catalog must not 500."""
    result = geo.predict_summit("mount-kirkpatrick", -84.3333, 166.4167)
    assert result["available"] is True
    assert result["input_source"] == geo.PLACEHOLDER_INPUT
    assert 0.0 <= result["probability"] <= 1.0


def test_turtle_mountain_refuses_placeholder():
    """The hill is outside the Washington stack, so a slug-seeded sample is not its ground."""
    result = geo.predict_summit("turtle-mountain", 49.57694, -114.41222)
    assert result.get("input_source") != geo.PLACEHOLDER_INPUT
    if result["available"]:
        assert result["input_source"] == geo.HILL_INPUT
    else:
        assert "placeholder" not in result["reason"]


def test_missing_artifacts_fail_soft(monkeypatch, tmp_path):
    monkeypatch.setattr(geo, "MODEL_PATH", tmp_path / "missing.txt")
    result = geo.predict_summit("anywhere", 0.0, 0.0)
    assert result["available"] is False
    assert result["probability"] is None
    assert "missing" in result["reason"]
