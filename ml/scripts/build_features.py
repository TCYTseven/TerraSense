#!/usr/bin/env python3
"""Build the terrain feature table for the susceptibility model (implementation steps 11 and 32).

Reads the step 10 rasters in data/raw/ and writes, relative to the repo root:
  data/processed/features.tif      7-band feature stack on one 30 m grid (UTM zone 10N)
  data/processed/features.parquet  labeled sample: pixels near landslide points (1) and
                                   random stable pixels (0), about 1:3, with a region id

For any other pack in ml/scripts/mountain_packs.py, --mountain SLUG builds the same stack
on a 30 m grid in that peak's own UTM zone, under data/processed/packs/<slug>/. Only
Rainier gets the labeled table: its landslide inventory is the only one dense enough to
train on, and the packs' knowledge-driven index must never look trained.

The stack covers every pixel, so step 12 can predict the full susceptibility map from it.
The labeled table needs data/seed/landslides.geojson; without it the script writes the
stack, says the table is pending, and exits 0.

Run from the repo root:
  python ml/scripts/build_features.py [--mountain SLUG] [--landslides PATH]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import mountain_packs as mp
import numpy as np
import pandas as pd
import rasterio
from pyproj import CRS
from pysheds.grid import Grid
from pysheds.sview import Raster, ViewFinder
from rasterio.transform import Affine, rowcol
from rasterio.warp import Resampling, reproject, transform, transform_bounds
from scipy.ndimage import distance_transform_edt

REPO_ROOT = Path(__file__).resolve().parents[2]

# The grid CRS is each pack's own UTM zone (Rainier: EPSG:32610): metric, so slope and
# distances come out in meters.
CELL_M = 30

# The seven model features, in band order.
FEATURES = ["elevation", "slope", "aspect", "curvature", "dist_drainage", "landcover", "twi"]

# A cell is a channel once this much area drains through it. 0.2 km2 keeps the steep,
# debris-flow-prone gullies without turning every hillside into a stream.
CHANNEL_AREA_M2 = 200_000

# Square blocks for the spatial train/test split in step 12 (250 cells = 7.5 km).
REGION_BLOCK_CELLS = 250

# Labels: pixels within this distance of a landslide point are positives.
POSITIVE_BUFFER_M = 50
# Negatives are drawn at least this far from every point, NEGATIVES_PER_POSITIVE per positive.
NEGATIVE_EXCLUSION_M = 500
NEGATIVES_PER_POSITIVE = 3
# News-geocoded catalog points are only useful as pixel labels when they are precise.
ACCEPTED_ACCURACY = {"exact", "1km"}
RANDOM_SEED = 11


def rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def utm_grid(bbox, grid_crs: str) -> tuple[Affine, int, int]:
    """The 30 m UTM grid that covers the bbox, snapped outward to whole cells."""
    left, bottom, right, top = transform_bounds("EPSG:4326", grid_crs, *bbox, densify_pts=21)
    left, bottom = np.floor(left / CELL_M) * CELL_M, np.floor(bottom / CELL_M) * CELL_M
    right, top = np.ceil(right / CELL_M) * CELL_M, np.ceil(top / CELL_M) * CELL_M
    width, height = int((right - left) / CELL_M), int((top - bottom) / CELL_M)
    return Affine(CELL_M, 0, left, 0, -CELL_M, top), width, height


def resample(path: Path, dst_transform: Affine, shape: tuple[int, int], grid_crs: str,
             resampling: Resampling, dtype: str) -> np.ndarray:
    """Reproject band 1 of a raster onto the grid. Cells outside the source become nodata."""
    fill = np.nan if dtype == "float32" else 0
    out = np.full(shape, fill, dtype=dtype)
    with rasterio.open(path) as src:
        reproject(
            source=rasterio.band(src, 1),
            destination=out,
            dst_transform=dst_transform,
            dst_crs=grid_crs,
            dst_nodata=fill,
            resampling=resampling,
        )
    return out


def neighbors(z: np.ndarray) -> tuple[np.ndarray, ...]:
    """The 3x3 neighborhood of every cell (a..i, row-major, north at the top), edges repeated."""
    p = np.pad(z, 1, mode="edge")
    return (p[:-2, :-2], p[:-2, 1:-1], p[:-2, 2:],
            p[1:-1, :-2], p[1:-1, 1:-1], p[1:-1, 2:],
            p[2:, :-2], p[2:, 1:-1], p[2:, 2:])


def slope_aspect(z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Horn (1981) slope in degrees and aspect as the compass bearing a slope faces (0 = north)."""
    a, b, c, d, _, f, g, h, i = neighbors(z)
    dz_east = ((c + 2 * f + i) - (a + 2 * d + g)) / (8 * CELL_M)
    dz_south = ((g + 2 * h + i) - (a + 2 * b + c)) / (8 * CELL_M)
    slope = np.degrees(np.arctan(np.hypot(dz_east, dz_south)))
    aspect = np.degrees(np.arctan2(-dz_east, dz_south)) % 360
    aspect[slope < 0.5] = np.nan  # a flat cell faces nowhere
    return slope.astype("float32"), aspect.astype("float32")


def curvature(z: np.ndarray) -> np.ndarray:
    """Zevenbergen and Thorne (1987) curvature, ArcGIS convention: negative = concave, units 1/100 m."""
    _, b, _, d, e, f, _, h, _ = neighbors(z)
    return (-200 * (((d + f) / 2 - e) + ((b + h) / 2 - e)) / CELL_M**2).astype("float32")


def fill_nearest(z: np.ndarray) -> np.ndarray:
    """Each NaN cell takes the value of the nearest valid cell.

    The grid's corners lie outside the DEM. Filled this way, the cells along that edge see the
    ground continue flat, as at the grid's outer edge. A constant fill would put a false cliff
    there, and slope, curvature, and wetness would all read it as terrain.
    """
    missing = np.isnan(z)
    if not missing.any():
        return z
    _, (rows, cols) = distance_transform_edt(missing, return_indices=True)
    return z[rows, cols]


def flow_accumulation(z: np.ndarray, dst_transform: Affine, grid_crs: str) -> np.ndarray:
    """D8 upstream cell count after filling pits and depressions and resolving flats."""
    dem = np.where(np.isnan(z), -9999.0, z).astype("float64")
    view = ViewFinder(affine=dst_transform, shape=z.shape, nodata=-9999.0, crs=CRS.from_user_input(grid_crs))
    grid = Grid.from_raster(Raster(dem, viewfinder=view))
    conditioned = grid.resolve_flats(grid.fill_depressions(grid.fill_pits(Raster(dem, viewfinder=view))))
    return np.asarray(grid.accumulation(grid.flowdir(conditioned)), dtype="float64")


def build_stack(pack: mp.Pack, paths: mp.PackPaths) -> tuple[np.ndarray, Affine]:
    """All seven features on the 30 m grid, shape (7, rows, cols)."""
    dst_transform, width, height = utm_grid(pack.bbox, pack.utm_crs)
    shape = (height, width)
    elevation = resample(paths.dem, dst_transform, shape, pack.utm_crs, Resampling.bilinear, "float32")
    landcover = resample(paths.landcover, dst_transform, shape, pack.utm_crs,
                         Resampling.mode, "uint8").astype("float32")
    landcover[landcover == 0] = np.nan  # WorldCover nodata

    filled = fill_nearest(elevation)
    slope, aspect = slope_aspect(filled)
    curv = curvature(filled)
    accumulation = flow_accumulation(elevation, dst_transform, pack.utm_crs)

    channels = accumulation * CELL_M**2 >= CHANNEL_AREA_M2
    dist_drainage = (distance_transform_edt(~channels) * CELL_M).astype("float32")
    # Topographic wetness index: ln(specific catchment area / tan(slope)).
    tan_slope = np.tan(np.radians(np.maximum(slope, 0.1)))
    twi = np.log(np.maximum(accumulation, 1) * CELL_M / tan_slope).astype("float32")

    stack = np.stack([elevation, slope, aspect, curv, dist_drainage, landcover, twi])
    stack[:, np.isnan(elevation)] = np.nan  # outside the DEM (grid corners beyond the bbox)
    return stack, dst_transform


def write_stack(stack: np.ndarray, dst_transform: Affine, grid_crs: str, stack_path: Path) -> None:
    stack_path.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff", "width": stack.shape[2], "height": stack.shape[1], "count": len(FEATURES),
        "dtype": "float32", "crs": grid_crs, "transform": dst_transform, "nodata": np.nan,
        "tiled": True, "blockxsize": 256, "blockysize": 256, "compress": "deflate", "predictor": 3,
    }
    with rasterio.open(stack_path, "w", **profile) as dst:
        dst.write(stack)
        for band, name in enumerate(FEATURES, start=1):
            dst.set_band_description(band, name)
        dst.update_tags(CHANNEL_AREA_M2=CHANNEL_AREA_M2, SOURCE="ml/scripts/build_features.py")


def region_ids(rows: np.ndarray, cols: np.ndarray, width: int) -> np.ndarray:
    blocks_per_row = int(np.ceil(width / REGION_BLOCK_CELLS))
    return (rows // REGION_BLOCK_CELLS) * blocks_per_row + cols // REGION_BLOCK_CELLS


def landslide_cells(path: Path, dst_transform: Affine, shape: tuple[int, int],
                    grid_crs: str) -> tuple[np.ndarray, int]:
    """Distance in meters from every cell to the nearest usable landslide point, and the point count."""
    features = json.loads(path.read_text(encoding="utf-8"))["features"]
    points = [f["geometry"]["coordinates"] for f in features
              if (f["properties"].get("location_accuracy") or "").lower() in ACCEPTED_ACCURACY]
    seeds = np.zeros(shape, dtype=bool)
    if points:
        xs, ys = transform("EPSG:4326", grid_crs, [p[0] for p in points], [p[1] for p in points])
        rows, cols = rowcol(dst_transform, xs, ys)
        for r, c in zip(rows, cols, strict=True):
            if 0 <= r < shape[0] and 0 <= c < shape[1]:
                seeds[r, c] = True
    distance = distance_transform_edt(~seeds) * CELL_M if seeds.any() else np.full(shape, np.inf)
    return distance, int(seeds.sum())


def build_table(stack: np.ndarray, dst_transform: Affine, landslides: Path,
                grid_crs: str) -> pd.DataFrame:
    """Positives within POSITIVE_BUFFER_M of a point, negatives sampled from stable ground."""
    shape = stack.shape[1:]
    distance, point_count = landslide_cells(landslides, dst_transform, shape, grid_crs)
    # Every band must be present, except aspect, which is NaN on flat ground by design.
    required = [i for i, name in enumerate(FEATURES) if name != "aspect"]
    valid = ~np.isnan(stack[required]).any(axis=0)
    positive = valid & (distance <= POSITIVE_BUFFER_M)
    if not positive.any():
        raise SystemExit(f"{rel(landslides)} has no usable points ({sorted(ACCEPTED_ACCURACY)}) inside the grid")

    candidates = np.flatnonzero(valid & (distance > NEGATIVE_EXCLUSION_M))
    rng = np.random.default_rng(RANDOM_SEED)
    n_negative = min(len(candidates), NEGATIVES_PER_POSITIVE * int(positive.sum()))
    negative = np.zeros(shape, dtype=bool)
    negative.flat[rng.choice(candidates, size=n_negative, replace=False)] = True

    rows, cols = np.nonzero(positive | negative)
    table = pd.DataFrame({name: stack[i, rows, cols] for i, name in enumerate(FEATURES)})
    table["label"] = positive[rows, cols].astype("int8")
    table["region"] = region_ids(rows, cols, shape[1]).astype("int16")
    table["row"], table["col"] = rows.astype("int32"), cols.astype("int32")
    print(f"  {point_count} landslide points used, {int(positive.sum())} positive and {n_negative} negative pixels")
    return table


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the terrain feature stack and labeled table.")
    parser.add_argument("--mountain", default=mp.RAINIER_SLUG,
                        help=f"pack slug from mountain_packs.py (default: {mp.RAINIER_SLUG})")
    parser.add_argument("--landslides", type=Path, default=None,
                        help="landslide points GeoJSON (default: the pack's seed file)")
    args = parser.parse_args()
    pack, paths = mp.get(args.mountain), mp.paths(args.mountain)
    landslides = args.landslides or paths.landslides

    stack, dst_transform = build_stack(pack, paths)
    write_stack(stack, dst_transform, pack.utm_crs, paths.stack)
    rows, cols = stack.shape[1:]
    print(f"wrote {rel(paths.stack)}: {len(FEATURES)} bands, {cols} x {rows} cells at {CELL_M} m, {pack.utm_crs}")
    for i, name in enumerate(FEATURES):
        band = stack[i]
        print(f"  {name:<13} min {np.nanmin(band):10.2f}  median {np.nanmedian(band):10.2f}  max {np.nanmax(band):10.2f}")

    if pack.slug != mp.RAINIER_SLUG:
        # Sparse catalog points elsewhere must never become a "trained" model (step 32 rule).
        print("labeled table skipped: only Rainier's landslide inventory is dense enough to train on")
        return
    if not landslides.exists():
        print(f"labeled table pending: {landslides} is missing. Run "
              "`python ml/scripts/download_sources.py --only landslides`, then rerun this script.")
        return
    table = build_table(stack, dst_transform, landslides, pack.utm_crs)
    table.to_parquet(paths.table, index=False)
    counts = table["label"].value_counts().to_dict()
    print(f"wrote {rel(paths.table)}: {len(table)} rows ({counts.get(1, 0)} positive, {counts.get(0, 0)} negative), "
          f"columns {list(table.columns)}, {table['region'].nunique()} regions")


if __name__ == "__main__":
    main()
