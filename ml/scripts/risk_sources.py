"""Source registry and cache primitives for the event-time risk pipeline.

Large scientific products are not committed to Git and several providers require credentials or
product-specific requests.  This module records exactly which normalized files were used and
provides a retrying, checksum-aware cache primitive instead of pretending a blocked download
succeeded.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw"
MANIFEST_PATH = RAW_DIR / "risk_sources_manifest.json"


@dataclass(frozen=True)
class SourceSpec:
    name: str
    family: str
    landing_page: str
    formats: tuple[str, ...]
    credential_required: bool
    operationally_suitable: bool
    notes: str


SOURCE_SPECS: dict[str, SourceSpec] = {
    "coolr": SourceSpec("NASA COOLR / Global Landslide Catalog", "labels", "https://gpm.nasa.gov/landslides", ("GeoJSON", "CSV"), False, True, "Filter to dated rainfall-related events; preserve event confidence and geometry."),
    "usgs_inventories_v3": SourceSpec("USGS Landslide Inventories Across the United States v3", "labels", "https://www.usgs.gov/programs/landslide-hazards/landslide-inventories-across-united-states", ("GeoJSON", "Shapefile", "Geodatabase"), False, True, "Use Date_Min/Date_Max only when uncertainty is within the configured label window."),
    "wgs_recent_landslides": SourceSpec("Washington Geological Survey Recent Landslides", "labels_audit", "https://gis.dnr.wa.gov/site3/rest/services/Geology/Landslide_Inventory_Database/MapServer/1", ("GeoJSON",), False, False, "Dated observation records without a reliable rainfall-trigger field; preserve as external audit labels only."),
    "copernicus_dem": SourceSpec("Copernicus DEM GLO-30", "static", "https://dataspace.copernicus.eu/", ("COG GeoTIFF",), False, True, "Aggregate source pixels into the configured prediction cell."),
    "soilgrids": SourceSpec("ISRIC SoilGrids 2.0", "static", "https://soilgrids.org/", ("Cloud Optimized GeoTIFF",), False, True, "Retain depth bands and uncertainty layers."),
    "worldcover": SourceSpec("ESA WorldCover 2021 v200", "static", "https://esa-worldcover.org/en/data-access", ("COG GeoTIFF",), False, True, "Aggregate class fractions, not a single arbitrary mode."),
    "osm": SourceSpec("OpenStreetMap", "static", "https://www.openstreetmap.org/", ("PBF", "GeoParquet", "GeoJSON"), False, True, "Road proximity is optional and always carries attribution."),
    "geology": SourceSpec("Regional/global geology adapter", "static", "https://www.usgs.gov/programs/energy-and-minerals", ("GeoTIFF", "GeoJSON", "GeoPackage"), False, False, "Schema varies by region; unavailable geology must be explicit."),
    "imerg": SourceSpec("NASA GPM IMERG V07", "historical_rain", "https://gpm.nasa.gov/data-access/downloads/gpm", ("HDF5", "NetCDF", "GeoTIFF"), True, True, "Use research-quality half-hour precipitation and training-period climatology."),
    "smap": SourceSpec("NASA SMAP L4", "soil_moisture", "https://nsidc.org/data/spl4smlgp/versions/7", ("HDF5", "NetCDF"), True, True, "Surface/root-zone values with age and quality flags; starts in 2015."),
    "era5_land": SourceSpec("ERA5-Land hourly", "hydrology", "https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land", ("NetCDF",), True, True, "Long-history fallback when SMAP is unavailable."),
    "gfs": SourceSpec("NOAA GFS", "forecast", "https://www.ncei.noaa.gov/products/weather-climate-models/global-forecast", ("GRIB2", "NetCDF"), False, True, "Persist model run time, lead, and forecast age."),
    "gefs_reforecast": SourceSpec("NOAA GEFSv12 reforecast", "forecast_reforecast", "https://registry.opendata.aws/noaa-gefs-reforecast/", ("GRIB2", "NetCDF"), False, True, "Use for historical forecast-realism evaluation, not realized rainfall."),
    "modis_snow": SourceSpec("MODIS MOD10A1 / MYD10A1", "snow", "https://nsidc.org/data/mod10a1/versions/61", ("HDF-EOS", "GeoTIFF"), False, True, "Cloud masks and missingness must be preserved."),
}


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    path: str
    sha256: str
    bytes: int
    downloaded_at: str
    source_url: str
    source_version: str | None
    temporal_start: str | None
    temporal_end: str | None
    spatial_resolution: str | None
    quality_flags: list[str]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_cached(url: str, output: Path, *, expected_sha256: str | None = None, retries: int = 3) -> SourceRecord:
    """Stream a source into a .part file, retrying transient errors and verifying the checksum."""
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.name + ".part")
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with requests.get(url, stream=True, timeout=(20, 180)) as response:
                response.raise_for_status()
                with partial.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1 << 20):
                        if chunk:
                            handle.write(chunk)
            digest = sha256(partial)
            if expected_sha256 and digest.lower() != expected_sha256.lower():
                partial.unlink(missing_ok=True)
                raise ValueError(f"checksum mismatch for {url}: expected {expected_sha256}, got {digest}")
            partial.replace(output)
            return SourceRecord(
                source_id=output.stem,
                path=str(output.relative_to(REPO_ROOT)),
                sha256=digest,
                bytes=output.stat().st_size,
                downloaded_at=datetime.now(UTC).isoformat(timespec="seconds"),
                source_url=url,
                source_version=None,
                temporal_start=None,
                temporal_end=None,
                spatial_resolution=None,
                quality_flags=[],
            )
        except (requests.RequestException, OSError, ValueError) as exc:
            last_error = exc
            partial.unlink(missing_ok=True)
            if attempt + 1 < retries:
                time.sleep(2**attempt)
    raise RuntimeError(f"source download failed after {retries} attempts: {last_error}") from last_error


def validate_hourly_table(path: Path, required: tuple[str, ...] = ("timestamp", "latitude", "longitude")) -> pd.DataFrame:
    """Read a normalized CSV/Parquet source and fail on missing coordinates or timestamps."""
    table = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)
    missing = sorted(set(required) - set(table.columns))
    if missing:
        raise ValueError(f"{path} missing normalized source columns: {missing}")
    timestamps = pd.to_datetime(table["timestamp"], utc=True, errors="coerce")
    if timestamps.isna().any():
        raise ValueError(f"{path} contains invalid timestamp values")
    if table[["latitude", "longitude"]].isna().any().any():
        raise ValueError(f"{path} contains missing coordinates")
    return table.assign(timestamp=timestamps).sort_values("timestamp").reset_index(drop=True)


def write_manifest(records: list[SourceRecord], path: Path = MANIFEST_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "sources": [asdict(record) for record in records]}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def source_manifest() -> dict[str, dict[str, Any]]:
    return {source_id: asdict(spec) for source_id, spec in SOURCE_SPECS.items()}
