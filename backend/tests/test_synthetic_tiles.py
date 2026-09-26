"""Synthetic map tiles for catalog mountains."""

from app.ml.synthetic_heatmap import render_synthetic_tile, synthetic_layer_metadata


def test_synthetic_metadata_stable():
    meta = synthetic_layer_metadata("cerro-bonete-chico", -70.998, 19.023, 6740)
    again = synthetic_layer_metadata("cerro-bonete-chico", -70.998, 19.023, 6740)
    assert meta["version"] == again["version"]
    assert meta["method"] == "seeded synthetic susceptibility"
    assert len(meta["bounds"]) == 4


def test_synthetic_tile_is_png():
    body = render_synthetic_tile("cerro-bonete-chico", -70.998, 19.023, 6740, 11, 327, 715)
    assert body[:8] == b"\x89PNG\r\n\x1a\n"
