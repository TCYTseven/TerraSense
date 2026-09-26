from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "ml" / "scripts"))

import risk_sources as sources  # noqa: E402


def test_registry_covers_required_source_families() -> None:
    expected = {"coolr", "usgs_inventories_v3", "copernicus_dem", "soilgrids", "worldcover", "osm", "imerg", "smap", "era5_land", "gfs", "gefs_reforecast", "modis_snow"}

    assert expected <= set(sources.SOURCE_SPECS)
    assert all(spec.landing_page.startswith("https://") for spec in sources.SOURCE_SPECS.values())


def test_hourly_source_validation_requires_normalized_coordinates_and_time(tmp_path: Path) -> None:
    path = tmp_path / "source.csv"
    pd.DataFrame({"timestamp": ["2026-01-01T00:00:00Z"], "latitude": [46.8], "longitude": [-121.7], "rain_mm": [1.0]}).to_csv(path, index=False)

    frame = sources.validate_hourly_table(path)

    assert str(frame.loc[0, "timestamp"].tz) == "UTC"

    bad = tmp_path / "bad.csv"
    pd.DataFrame({"timestamp": ["not-a-time"], "latitude": [46.8]}).to_csv(bad, index=False)
    with pytest.raises(ValueError, match="missing normalized source columns"):
        sources.validate_hourly_table(bad)
