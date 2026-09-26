from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "ml" / "scripts"))

import build_static_features as static_features  # noqa: E402


def test_static_builder_aggregates_source_pixels_to_prediction_cells(tmp_path: Path) -> None:
    path = tmp_path / "features.tif"
    transform = from_origin(500_000, 5_200_000, 30, 30)
    bands = np.stack([
        np.full((8, 8), 1000, dtype="float32"),
        np.full((8, 8), 25, dtype="float32"),
        np.full((8, 8), 180, dtype="float32"),
        np.zeros((8, 8), dtype="float32"),
        np.full((8, 8), 50, dtype="float32"),
        np.full((8, 8), 10, dtype="float32"),
        np.full((8, 8), 8, dtype="float32"),
    ])
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=8,
        height=8,
        count=7,
        dtype="float32",
        crs="EPSG:32610",
        transform=transform,
        nodata=np.nan,
    ) as dataset:
        dataset.write(bands)
        for index, name in enumerate(("elevation", "slope", "aspect", "curvature", "dist_drainage", "landcover", "twi"), start=1):
            dataset.set_band_description(index, name)

    table = static_features.build_static_table(path)

    assert len(table) == 1
    assert table.loc[0, "dem_available"] == 1
    assert table.loc[0, "worldcover_available"] == 1
    assert table.loc[0, "slope_mean"] == 25
    assert table.loc[0, "forest_fraction"] == 1
    assert table.loc[0, "soilgrids_available"] == 0
    assert np.isnan(table.loc[0, "road_distance_m"])
