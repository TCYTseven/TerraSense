"""A click inside Turtle Mountain stays fail-closed and reads that hill's raster."""

import numpy as np
import pytest
from pyproj import Transformer
from rasterio.transform import from_origin

from app.hills import TURTLE_BBOX, TURTLE_SLUG, hill_probability_path, hill_susceptibility_path
from app.ml import risk_inference
from app.ml.probability import ProbabilityMap, write
from app.packs import probability_path, susceptibility_path
from app.risk import cap_probability
from app.risk_summary import risk_summary

from .conftest import storm_rain

SUMMIT = (49.57694, -114.41222)


def _summit_grid(value: float) -> ProbabilityMap:
    x, y = Transformer.from_crs("EPSG:4326", "EPSG:32611", always_xy=True).transform(SUMMIT[1], SUMMIT[0])
    transform = from_origin(x - 45, y + 45, 30, 30)
    values = np.full((3, 3), value, dtype="float32")
    return ProbabilityMap(values, transform, "EPSG:32611", "regional LightGBM and Model B")


def test_hill_rasters_do_not_replace_rainier():
    assert hill_probability_path(TURTLE_SLUG) != probability_path("mount-rainier")
    assert hill_susceptibility_path(TURTLE_SLUG) != susceptibility_path("mount-rainier")


def test_a_click_in_the_hill_box_reads_the_hill_raster_without_washington_skill():
    rain = storm_rain()
    grid = _summit_grid(0.62)
    prediction = risk_inference.predict_location(
        *SUMMIT, rain_override=rain, probability_override=grid,
    )

    assert prediction.state == "UNCERTAIN"
    assert "OUT_OF_DISTRIBUTION" in prediction.reason_codes
    assert prediction.calibrated_probability is None
    assert prediction.probability == pytest.approx(0.62, abs=1e-4)
    assert prediction.probability_source == "model_b_estimate"
    assert prediction.estimate["validation"] is None
    assert prediction.estimate["method"] == "regional LightGBM and Model B"


def test_a_hill_with_no_trails_scores_the_map(db_conn, tmp_path):
    saved = _summit_grid(0.55)
    saved_values = saved.values.copy()
    saved_values[0, 0] = 0.81
    path = tmp_path / "probability.tif"
    write(ProbabilityMap(saved_values, saved.transform, saved.crs, saved.method), path)

    summary = risk_summary(db_conn, TURTLE_SLUG, path)

    assert summary["overall"]["trails_scored"] == 0
    assert summary["trails"] == []
    assert summary["overall"]["score"] == pytest.approx(cap_probability(0.81), abs=1e-4)
    assert summary["bbox"] == list(TURTLE_BBOX)
    assert summary["method"] == "regional LightGBM and Model B"
