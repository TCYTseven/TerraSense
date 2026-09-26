"""Adversarial contract tests for the terrain feature and label builder."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from rasterio.transform import Affine, xy
from rasterio.warp import transform

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "ml" / "scripts"))

import build_features as features  # noqa: E402


def geojson_point_for_cell(dst_transform: Affine, row: int, col: int) -> list[float]:
    """Return a WGS84 point at a synthetic UTM raster cell center."""
    east, north = xy(dst_transform, row, col, offset="center")
    lon, lat = transform(features.GRID_CRS, "EPSG:4326", [east], [north])
    return [lon[0], lat[0]]


def write_inventory(path: Path, dst_transform: Affine, row: int, col: int) -> None:
    path.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "usable",
                "geometry": {"type": "Point", "coordinates": geojson_point_for_cell(dst_transform, row, col)},
                "properties": {"location_accuracy": "1km"},
            },
            {
                "type": "Feature",
                "id": "rejected",
                "geometry": {"type": "Point", "coordinates": geojson_point_for_cell(dst_transform, row, col + 1)},
                "properties": {"location_accuracy": "country"},
            },
        ],
    }), encoding="utf-8")


def test_region_ids_keep_spatial_blocks_together() -> None:
    rows = np.array([0, 249, 250, 500])
    cols = np.array([0, 249, 0, 500])

    regions = features.region_ids(rows, cols, width=1004)

    assert regions.tolist() == [0, 0, 5, 12]
    assert regions[0] == regions[1]
    assert regions[1] != regions[2]


def test_landslide_cells_only_accepts_declared_accuracies(tmp_path: Path) -> None:
    dst_transform = Affine(30, 0, 500_000, 0, -30, 5_200_000)
    inventory = tmp_path / "landslides.geojson"
    write_inventory(inventory, dst_transform, row=10, col=10)

    distance, point_count = features.landslide_cells(inventory, dst_transform, (40, 40))

    assert point_count == 1
    assert distance[10, 10] == 0
    assert distance[10, 11] > 0


def test_build_table_has_binary_labels_and_exclusion_zone(tmp_path: Path) -> None:
    dst_transform = Affine(30, 0, 500_000, 0, -30, 5_200_000)
    inventory = tmp_path / "landslides.geojson"
    write_inventory(inventory, dst_transform, row=20, col=20)
    stack = np.ones((len(features.FEATURES), 40, 40), dtype="float32")

    table = features.build_table(stack, dst_transform, inventory)

    assert list(table.columns) == features.FEATURES + ["label", "region", "row", "col"]
    assert set(table["label"]) == {0, 1}
    assert table["label"].sum() > 0
    assert (table.loc[table["label"] == 0, "row"] - 20).abs().max() > 16
    assert table[["row", "col"]].duplicated().sum() == 0
