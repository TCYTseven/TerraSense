"""Tests for the read-only deployment artifact validator."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "ml" / "scripts"))

import validate_pipeline as audit  # noqa: E402


def test_current_artifacts_pass_the_full_audit() -> None:
    summary = audit.validate(require_probability=True)

    assert summary["labels"] == 37
    assert summary["usable_labels"] == 34
    assert summary["feature_rows"] == 1224
    assert summary["susceptibility_tiles"] == 383
    assert summary["probability_tiles"] == 383


def test_raster_audit_rejects_values_outside_probability_range(tmp_path: Path) -> None:
    path = tmp_path / "bad.tif"
    transform = Affine(30, 0, 500_000, 0, -30, 5_200_000)
    with rasterio.open(
        path, "w", driver="GTiff", width=2, height=2, count=1, dtype="float32",
        crs="EPSG:32610", transform=transform, nodata=np.nan,
    ) as dst:
        dst.write(np.array([[0.1, 1.2], [0.2, np.nan]], dtype="float32"), 1)

    errors: list[str] = []
    audit._check_raster(path, "bad", (2, 2), transform, rasterio.crs.CRS.from_epsg(32610), errors)

    assert any("invalid values" in error for error in errors)
