"""A click inside a demo pack bbox reads that pack's raster outside Rainier."""

import pytest

from app.ml import risk_inference
from app.packs import pack_covering

KAILASH_SUMMIT = (31.0672, 81.3119)


def test_kailash_summit_is_covered_by_its_pack():
    assert pack_covering(*KAILASH_SUMMIT) == "mount-kailash"


def test_a_click_on_kailash_gets_a_map_estimate_not_study_box_only():
    from .conftest import storm_rain

    prediction = risk_inference.predict_location(
        *KAILASH_SUMMIT,
        rain_override=storm_rain(),
        mountain_slug="mount-kailash",
    )

    assert "OUT_OF_DISTRIBUTION" in prediction.reason_codes
    assert prediction.state == "UNCERTAIN"
    assert prediction.calibrated_probability is None
    assert prediction.probability is not None
    assert prediction.probability_source == "model_b_estimate"
    assert prediction.estimate is not None
    assert prediction.estimate["validation"] is None
