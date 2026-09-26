#!/usr/bin/env python3
"""Aggregate static rasters into the canonical 1 km prediction-cell table.

The existing ``features.tif`` is intentionally retained for the legacy map.  This builder creates
the separate production static contract: source pixels are grouped by metric cell and summarized,
so a 30 m source never masquerades as 30 m prediction precision.  Optional SoilGrids rasters can
be supplied as ``canonical_feature=path`` arguments; absent optional layers stay null and are
recorded as unavailable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from scipy.ndimage import maximum_filter, minimum_filter, uniform_filter
from rasterio.enums import Resampling
from rasterio.warp import reproject

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.ml.risk_contract import MODEL_FEATURES, STATIC_FEATURES  # noqa: E402
from app.ml.risk_features import event_cell_id  # noqa: E402

DEFAULT_STACK = REPO_ROOT / "data" / "processed" / "features.tif"
DEFAULT_OUT = REPO_ROOT / "data" / "processed" / "static" / "static_cells.parquet"
DEFAULT_JSON = REPO_ROOT / "data" / "processed" / "static" / "static_cells.json"
GRID_CRS = "EPSG:32610"
CELL_SIZE_M = 1000
WORLD_COVER_CLASSES = {
    "forest_fraction": (10,),
    "shrub_fraction": (20,),
    "grassland_fraction": (30,),
    "cropland_fraction": (40,),
    "built_fraction": (50,),
    "bare_fraction": (60,),
    "snow_ice_fraction": (70,),
    "water_fraction": (80,),
}


def _clean(values: pd.Series) -> np.ndarray:
    return pd.to_numeric(values, errors="coerce").to_numpy(dtype="float64")


def _raster_on_grid(path: Path, shape: tuple[int, int], transform, crs: str) -> np.ndarray:
    with rasterio.open(path) as src:
        destination = np.full(shape, np.nan, dtype="float32")
        reproject(
            source=rasterio.band(src, 1),
            destination=destination,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=src.nodata,
            dst_transform=transform,
            dst_crs=crs,
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )
    return destination


def _cell_frame(stack_path: Path) -> tuple[pd.DataFrame, dict[str, np.ndarray], object]:
    with rasterio.open(stack_path) as dataset:
        arrays = dataset.read().astype("float64")
        descriptions = list(dataset.descriptions)
        transform = dataset.transform
        crs = str(dataset.crs)
    bands = {name: arrays[index] for index, name in enumerate(descriptions) if name}
    elevation = bands.get("elevation")
    if elevation is None:
        raise ValueError("static feature stack needs a band named elevation")
    rows, cols = np.indices(elevation.shape)
    east, north = rasterio.transform.xy(transform, rows, cols, offset="center")
    east = np.asarray(east, dtype="float64").reshape(elevation.shape)
    north = np.asarray(north, dtype="float64").reshape(elevation.shape)
    valid = np.isfinite(elevation)
    frame = pd.DataFrame({
        "cell_id": [event_cell_id(x, y, CELL_SIZE_M) for x, y in zip(east[valid], north[valid], strict=True)],
        "easting_m": east[valid],
        "northing_m": north[valid],
    })
    for name, values in bands.items():
        frame[name] = values[valid]
    return frame, bands, (transform, crs, elevation.shape)


def build_static_table(stack_path: Path, soilgrids: dict[str, Path] | None = None) -> pd.DataFrame:
    frame, bands, (transform, crs, shape) = _cell_frame(stack_path)
    grouped = frame.groupby("cell_id", sort=True)
    table = grouped[[name for name in ("elevation", "slope", "aspect", "curvature", "dist_drainage", "twi") if name in frame]].agg(["mean", "std", "max"])
    table.columns = [f"{left}_{right}" for left, right in table.columns]
    out = pd.DataFrame(index=table.index)

    def stat(source: str, aggregate: str = "mean") -> pd.Series:
        key = f"{source}_{aggregate}"
        return table[key] if key in table else pd.Series(np.nan, index=table.index)

    out["elevation_mean"] = stat("elevation")
    out["elevation_std"] = stat("elevation", "std")
    out["slope_mean"] = stat("slope")
    out["slope_max"] = stat("slope", "max")
    out["slope_p90"] = grouped["slope"].quantile(0.90) if "slope" in frame else np.nan
    out["aspect_sin_mean"] = grouped["aspect"].apply(lambda values: np.nanmean(np.sin(np.deg2rad(_clean(values)))) if np.isfinite(_clean(values)).any() else np.nan) if "aspect" in frame else np.nan
    out["aspect_cos_mean"] = grouped["aspect"].apply(lambda values: np.nanmean(np.cos(np.deg2rad(_clean(values)))) if np.isfinite(_clean(values)).any() else np.nan) if "aspect" in frame else np.nan
    out["profile_curvature_mean"] = stat("curvature")
    out["plan_curvature_mean"] = stat("curvature")
    out["twi_mean"] = stat("twi")
    out["dist_drainage_mean"] = stat("dist_drainage")

    elevation = bands.get("elevation")
    if elevation is not None:
        # These are neighborhood summaries on the source grid, then aggregated to the cell.
        filled = np.where(np.isfinite(elevation), elevation, np.nanmedian(elevation))
        source_resolution = max(abs(float(transform.a)), abs(float(transform.e)))
        roughness = uniform_filter(filled, size=3, mode="nearest")
        out["roughness_mean"] = pd.Series((np.abs(filled - roughness))[np.isfinite(elevation)]).groupby(frame["cell_id"]).mean()
        out["terrain_ruggedness_mean"] = out["roughness_mean"]
        for distance, name in ((100, "local_relief_100m"), (500, "local_relief_500m"), (1000, "local_relief_1km")):
            width = max(3, int(round(distance / source_resolution)) | 1)
            relief = maximum_filter(filled, size=width, mode="nearest") - minimum_filter(filled, size=width, mode="nearest")
            out[name] = pd.Series(relief[np.isfinite(elevation)]).groupby(frame["cell_id"]).mean()
    else:
        for name in ("roughness_mean", "terrain_ruggedness_mean", "local_relief_100m", "local_relief_500m", "local_relief_1km"):
            out[name] = np.nan
    out["flow_accumulation_mean"] = np.nan

    if "landcover" in frame:
        for name, codes in WORLD_COVER_CLASSES.items():
            out[name] = grouped["landcover"].apply(lambda values, codes=codes: float(np.isin(_clean(values), codes).mean()))
    else:
        for name in WORLD_COVER_CLASSES:
            out[name] = np.nan

    for name in ("soil_clay_0_30", "soil_sand_0_30", "soil_silt_0_30", "soil_bulk_density_0_30", "soil_coarse_fragments_0_30", "soil_organic_carbon_0_30"):
        out[name] = np.nan

    # Road and geology are optional adapters. Their absence is explicit in both the row and the
    # availability flag; no zero is substituted for an unknown distance or lithology.
    for name in ("road_distance_m", "road_density_km_km2", "major_road_density_km_km2", "geology_class_encoded", "fault_distance_m"):
        out[name] = np.nan

    if soilgrids:
        for feature, path in soilgrids.items():
            if feature not in STATIC_FEATURES:
                raise ValueError(f"{feature} is not a canonical static feature")
            if not path.is_file():
                raise FileNotFoundError(path)
            layer = _raster_on_grid(path, shape, transform, crs)
            valid = np.isfinite(layer)
            if valid.any():
                values = pd.Series(layer[valid], dtype="float64")
                keys = pd.Series([event_cell_id(x, y, CELL_SIZE_M) for x, y in zip(
                    np.asarray(rasterio.transform.xy(transform, *np.where(valid), offset="center")[0]),
                    np.asarray(rasterio.transform.xy(transform, *np.where(valid), offset="center")[1]),
                    strict=True,
                )])
                out[feature] = values.groupby(keys).mean()

    center = frame.groupby("cell_id")[["easting_m", "northing_m"]].mean()
    to_wgs84 = Transformer.from_crs(GRID_CRS, "EPSG:4326", always_xy=True)
    longitude, latitude = to_wgs84.transform(center["easting_m"].to_numpy(), center["northing_m"].to_numpy())
    out["longitude"] = longitude
    out["latitude"] = latitude
    out["dem_available"] = out["elevation_mean"].notna().astype("float32")
    out["worldcover_available"] = out["forest_fraction"].notna().astype("float32")
    out["soilgrids_available"] = out[["soil_clay_0_30", "soil_sand_0_30", "soil_silt_0_30", "soil_bulk_density_0_30", "soil_coarse_fragments_0_30", "soil_organic_carbon_0_30"]].notna().all(axis=1).astype("float32")
    out = out.reset_index()
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack", type=Path, default=DEFAULT_STACK)
    parser.add_argument("--soilgrids", action="append", default=[], metavar="FEATURE=PATH")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--json-out", type=Path, default=DEFAULT_JSON)
    args = parser.parse_args()
    soilgrids = {}
    for item in args.soilgrids:
        feature, separator, path = item.partition("=")
        if not separator or not feature or not path:
            raise ValueError(f"--soilgrids must be FEATURE=PATH, got {item!r}")
        soilgrids[feature] = Path(path)
    table = build_static_table(args.stack, soilgrids)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(args.out, index=False)
    records = table.astype(object).where(pd.notna(table), None).to_dict(orient="records")
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(records, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "json_out": str(args.json_out), "cells": len(table), "soilgrids": sorted(soilgrids)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
