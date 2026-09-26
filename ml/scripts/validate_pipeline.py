#!/usr/bin/env python3
"""Validate the complete Rainier ML artifact set before deployment.

This is intentionally a read-only audit. It checks the committed seed labels, downloaded
source coverage, derived feature/table contracts, trained model card and raster, and every
rendered susceptibility tile. ``--require-probability`` additionally verifies the latest live
Model B raster and tile set.

Run from the repository root:
  python ml/scripts/validate_pipeline.py --require-probability
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from PIL import Image
from rasterio.warp import transform_bounds
from shapely.geometry import shape

REPO_ROOT = Path(__file__).resolve().parents[2]
BBOX = (-121.93, 46.76, -121.54, 46.96)
FEATURES = ["elevation", "slope", "aspect", "curvature", "dist_drainage", "landcover", "twi"]
TABLE_COLUMNS = FEATURES + ["label", "region", "row", "col"]

SOURCES = {
    "DEM": REPO_ROOT / "data/raw/rainier_dem_cop30.tif",
    "land cover": REPO_ROOT / "data/raw/rainier_landcover_worldcover2021.tif",
}
LANDSLIDES = REPO_ROOT / "data/seed/landslides.geojson"
FEATURE_STACK = REPO_ROOT / "data/processed/features.tif"
FEATURE_TABLE = REPO_ROOT / "data/processed/features.parquet"
ARTIFACTS = REPO_ROOT / "ml/artifacts"


def _inside(lon: float, lat: float) -> bool:
    west, south, east, north = BBOX
    return west <= lon <= east and south <= lat <= north


def _check_source(path: Path, name: str, errors: list[str]) -> None:
    if not path.is_file():
        errors.append(f"{name} missing: {path.relative_to(REPO_ROOT)}")
        return
    try:
        with rasterio.open(path) as source:
            bounds = transform_bounds(source.crs, "EPSG:4326", *source.bounds)
            if not (bounds[0] <= BBOX[0] and bounds[1] <= BBOX[1]
                    and bounds[2] >= BBOX[2] and bounds[3] >= BBOX[3]):
                errors.append(f"{name} does not cover the shared Rainier bbox: {bounds}")
    except Exception as exc:  # pragma: no cover - reports corrupt deployment input
        errors.append(f"{name} cannot be opened: {type(exc).__name__}: {exc}")


def _check_seed(errors: list[str]) -> int:
    if not LANDSLIDES.is_file():
        errors.append("landslide seed is missing")
        return 0
    try:
        payload = json.loads(LANDSLIDES.read_text(encoding="utf-8"))
        features = payload["features"]
        if payload.get("type") != "FeatureCollection" or not features:
            errors.append("landslide seed is not a non-empty FeatureCollection")
            return 0
        for feature in features:
            geometry = shape(feature["geometry"])
            if geometry.geom_type != "Point":
                errors.append(f"landslide {feature.get('id')} is not a Point")
            lon, lat = geometry.coords[0]
            if not _inside(lon, lat):
                errors.append(f"landslide {feature.get('id')} is outside the shared bbox")
            if feature.get("properties", {}).get("location_accuracy") not in {"exact", "1km"}:
                errors.append(f"landslide {feature.get('id')} has unusable location accuracy")
        return len(features)
    except (AttributeError, OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"landslide seed is invalid: {type(exc).__name__}: {exc}")
        return 0


def _check_grid(errors: list[str]) -> tuple[tuple[int, int], object | None, object | None]:
    if not FEATURE_STACK.is_file():
        errors.append("feature stack is missing")
        return (0, 0), None, None
    try:
        with rasterio.open(FEATURE_STACK) as stack:
            if list(stack.descriptions) != FEATURES:
                errors.append(f"feature bands do not match {FEATURES}: {stack.descriptions}")
            if stack.crs.to_string() != "EPSG:32610":
                errors.append(f"feature CRS is {stack.crs}, expected EPSG:32610")
            bounds = transform_bounds(stack.crs, "EPSG:4326", *stack.bounds)
            if not (bounds[0] <= BBOX[0] and bounds[1] <= BBOX[1]
                    and bounds[2] >= BBOX[2] and bounds[3] >= BBOX[3]):
                errors.append(f"feature stack does not cover the shared bbox: {bounds}")
            return (stack.height, stack.width), stack.transform, stack.crs
    except Exception as exc:  # pragma: no cover - reports corrupt deployment input
        errors.append(f"feature stack cannot be opened: {type(exc).__name__}: {exc}")
        return (0, 0), None, None


def _check_table(errors: list[str]) -> int:
    if not FEATURE_TABLE.is_file():
        errors.append("feature table is missing")
        return 0
    try:
        table = pd.read_parquet(FEATURE_TABLE)
        missing = [column for column in TABLE_COLUMNS if column not in table.columns]
        if missing:
            errors.append(f"feature table is missing columns: {missing}")
        labels = set(table["label"].dropna().unique().tolist())
        if not labels <= {0, 1}:
            errors.append(f"feature table labels are not binary: {sorted(labels)}")
        required_values = [name for name in TABLE_COLUMNS if name != "aspect"]
        if table[required_values].isna().any().any():
            errors.append("feature table contains missing values outside the optional flat-cell aspect")
        if table[["row", "col"]].duplicated().any():
            errors.append("feature table contains duplicate pixel coordinates")
        if table["region"].isna().any():
            errors.append("feature table contains null spatial regions")
        return len(table)
    except Exception as exc:  # pragma: no cover - reports corrupt deployment input
        errors.append(f"feature table cannot be opened: {type(exc).__name__}: {exc}")
        return 0


def _check_raster(path: Path, name: str, shape: tuple[int, int], transform: object, crs: object,
                  errors: list[str]) -> int:
    if not path.is_file():
        errors.append(f"{name} raster is missing: {path.relative_to(REPO_ROOT)}")
        return 0
    try:
        with rasterio.open(path) as raster:
            if (raster.height, raster.width) != shape:
                errors.append(f"{name} shape {raster.shape} does not match feature grid {shape}")
            if raster.transform != transform or raster.crs != crs:
                errors.append(f"{name} georeferencing does not match the feature grid")
            values = raster.read(1, masked=True).filled(np.nan)
            valid = values[np.isfinite(values)]
            if not valid.size or not np.isfinite(valid).all() or valid.min() < 0 or valid.max() > 1:
                errors.append(f"{name} contains invalid values outside 0..1 or no valid cells")
            return int(valid.size)
    except Exception as exc:  # pragma: no cover - reports corrupt deployment input
        errors.append(f"{name} cannot be opened: {type(exc).__name__}: {exc}")
        return 0


def _check_tiles(layer: str, method: str, errors: list[str]) -> int:
    directory = REPO_ROOT / "backend/tiles" / layer
    metadata_path = directory / "metadata.json"
    if not metadata_path.is_file():
        errors.append(f"{layer} tile metadata is missing")
        return 0
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("method") != method:
            errors.append(f"{layer} tiles use {metadata.get('method')!r}, expected {method!r}")
        paths = sorted(directory.glob("*/*/*.png"))
        if len(paths) != metadata.get("tile_count"):
            errors.append(f"{layer} metadata tile_count disagrees with files")
        for path in paths:
            with Image.open(path) as image:
                if image.format != "PNG" or image.size != (256, 256):
                    errors.append(f"invalid {layer} tile: {path.relative_to(REPO_ROOT)}")
        return len(paths)
    except Exception as exc:  # pragma: no cover - reports corrupt deployment input
        errors.append(f"{layer} tile set is invalid: {type(exc).__name__}: {exc}")
        return 0


def validate(require_probability: bool = False) -> dict[str, int | float | str]:
    """Return a compact audit summary or raise ``SystemExit`` with every failure."""
    errors: list[str] = []
    for name, path in SOURCES.items():
        _check_source(path, name, errors)
    labels = _check_seed(errors)
    grid_shape, transform, crs = _check_grid(errors)
    rows = _check_table(errors)

    metrics_path = ARTIFACTS / "metrics.json"
    model_path = ARTIFACTS / "susceptibility_lgbm.txt"
    try:
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        if metrics.get("trained") is not True or metrics.get("method") != "lightgbm":
            errors.append("metrics.json does not describe a trained LightGBM model")
        if not isinstance(metrics.get("auc"), (int, float)) or not 0 <= metrics["auc"] <= 1:
            errors.append("metrics.json has no bounded AUC")
        if metrics.get("features") != FEATURES:
            errors.append("metrics.json feature list does not match the feature stack")
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"metrics.json is invalid: {type(exc).__name__}: {exc}")
        metrics = {"method": "lightgbm", "auc": 0}
    if not model_path.is_file() or model_path.stat().st_size < 100_000:
        errors.append("trained LightGBM model artifact is missing or implausibly small")

    susceptibility_cells = _check_raster(
        ARTIFACTS / "susceptibility.tif", "susceptibility", grid_shape, transform, crs, errors)
    susceptibility_tiles = _check_tiles("susceptibility", str(metrics.get("method")), errors)
    probability_cells = 0
    probability_tiles = 0
    if require_probability:
        probability_cells = _check_raster(
            ARTIFACTS / "probability.tif", "probability", grid_shape, transform, crs, errors)
        probability_tiles = _check_tiles("probability", "model b", errors)

    if errors:
        raise SystemExit("ML deployment audit failed:\n- " + "\n- ".join(errors))
    return {
        "labels": labels,
        "feature_rows": rows,
        "susceptibility_cells": susceptibility_cells,
        "susceptibility_tiles": susceptibility_tiles,
        "probability_cells": probability_cells,
        "probability_tiles": probability_tiles,
        "auc": float(metrics["auc"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the complete Rainier ML deployment artifact set.")
    parser.add_argument("--require-probability", action="store_true",
                        help="also require the latest Model B probability raster and tiles")
    args = parser.parse_args()
    summary = validate(args.require_probability)
    print("ML deployment audit passed:", json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
