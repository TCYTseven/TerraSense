"""The model ceiling: no score leaves the backend above 0.80, and levels do not move."""

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from app.ml import pressure
from app.ml.probability import ProbabilityMap, cap_grid, write
from app.risk import PROBABILITY_CEILING, PROBABILITY_KNEE, cap_probability, risk_level
from app.risk_summary import saved_map

GRID = np.linspace(0.0, 1.0, 1001)


def _map(values: np.ndarray, **kwargs) -> ProbabilityMap:
    return ProbabilityMap(np.asarray(values, dtype="float32"), from_origin(500000, 5200000, 30, 30),
                          "EPSG:32610", "test", **kwargs)


def test_scores_at_or_below_the_knee_are_untouched():
    for p in (0.0, 0.1, 0.2, 0.45, 0.6, PROBABILITY_KNEE):
        assert cap_probability(p) == pytest.approx(p)


@pytest.mark.parametrize(("raw", "capped"), [(1.0, 0.80), (0.93, 0.7767), (0.85, 0.75), (0.75, 0.7167)])
def test_high_scores_squeeze_into_the_top_band(raw, capped):
    assert cap_probability(raw) == pytest.approx(capped, abs=1e-4)


def test_cap_is_monotonic_bounded_and_keeps_every_level():
    capped = [cap_probability(p) for p in GRID]
    assert all(b >= a for a, b in zip(capped, capped[1:], strict=False))
    assert max(capped) == pytest.approx(PROBABILITY_CEILING)
    assert all(risk_level(c) == risk_level(p) for p, c in zip(GRID, capped, strict=True))
    assert cap_probability(1.7) == pytest.approx(PROBABILITY_CEILING)
    assert cap_probability(-0.3) == 0.0


def test_grid_cap_matches_the_scalar_and_keeps_nan():
    values = np.append(GRID, np.nan).astype("float32")
    capped = cap_grid(values)
    assert np.isnan(capped[-1])
    np.testing.assert_allclose(capped[:-1], [cap_probability(p) for p in values[:-1]], atol=1e-6)


def test_every_probability_map_is_capped_once():
    grid = _map(np.array([[0.1, 0.93], [1.0, np.nan]]))
    assert grid.capped
    assert float(np.nanmax(grid.values)) == pytest.approx(PROBABILITY_CEILING)
    assert grid.values[0, 1] == pytest.approx(0.7767, abs=1e-4)
    already = _map(grid.values, capped=True)
    np.testing.assert_array_equal(already.values, grid.values)


def test_a_saved_map_reads_back_without_a_second_squeeze(tmp_path):
    path = tmp_path / "probability.tif"
    write(_map(np.array([[0.93, 0.5]])), path)
    loaded, _written = saved_map(path)
    assert loaded.values[0, 0] == pytest.approx(0.7767, abs=1e-4)
    assert loaded.values[0, 1] == pytest.approx(0.5)


def test_a_map_saved_before_the_cap_is_capped_on_read(tmp_path):
    path = tmp_path / "legacy.tif"
    profile = {"driver": "GTiff", "width": 2, "height": 1, "count": 1, "dtype": "float32",
               "crs": "EPSG:32610", "transform": from_origin(500000, 5200000, 30, 30), "nodata": np.nan}
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(np.array([[1.0, 0.3]], dtype="float32"), 1)
        dst.update_tags(METHOD="old")
    loaded, _written = saved_map(path)
    assert loaded.values[0, 0] == pytest.approx(PROBABILITY_CEILING)
    assert loaded.values[0, 1] == pytest.approx(0.3)


def test_trail_grade_peaks_stay_under_the_ceiling():
    assert pressure.peak_for_steepness(10_000) == pytest.approx(cap_probability(0.92))
    assert pressure.peak_for_steepness(10_000) <= PROBABILITY_CEILING
