"""The live regional-model seam: real pixel parity with the baked map, and fail-closed off-stack peaks.

The parity test is the sync check for the whole feature: the backend's live prediction at a
stack pixel must equal the value apply_susceptibility_map.py baked into susceptibility.tif,
so the agents and the catalog quote the same model the heat map draws.
"""

import json

import numpy as np
import pytest
import rasterio

from app.ml import geo_susceptibility as geo
from app.risk import cap_probability

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
        assert result["probability"] == pytest.approx(cap_probability(expected), abs=2e-4)


def test_outside_stack_summit_is_unavailable():
    result = geo.predict_summit("mount-everest", *EVEREST_PEAK)
    assert result["available"] is False
    assert result["probability"] is None
    assert result["input_source"] is None
    assert "outside the regional feature stack" in result["reason"]


def test_polar_summit_outside_stack_is_unavailable():
    """Antarctic peaks are outside the Rainier UTM stack; catalog must not invent terrain."""
    result = geo.predict_summit("mount-kirkpatrick", -84.3333, 166.4167)
    assert result["available"] is False
    assert result["probability"] is None


def test_turtle_mountain_uses_hill_window_or_unavailable():
    """The hill is outside the Washington stack; only its own raster may score it."""
    result = geo.predict_summit("turtle-mountain", 49.57694, -114.41222)
    if result["available"]:
        assert "feature window" in result["input_source"]
        assert result["model_card"]["auc"] is None
    else:
        assert "hill terrain window" in result["reason"]


def test_missing_artifacts_fail_soft(monkeypatch, tmp_path):
    monkeypatch.setattr(geo, "MODEL_PATH", tmp_path / "missing.txt")
    result = geo.predict_summit("anywhere", 0.0, 0.0)
    assert result["available"] is False
    assert result["probability"] is None
    assert "missing" in result["reason"]
