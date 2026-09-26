#!/usr/bin/env python3
"""Download the DEM and land cover for the regional susceptibility model.

Reads windows of the public Copernicus DEM GLO-30 and ESA WorldCover 2021 v200 COGs over HTTP
range requests (no key) and writes, relative to the repo root:
  data/raw/region_dem_cop30.tif                  GLO-30 mosaic over DOWNLOAD_BBOX, EPSG:4326
  data/raw/region_landcover_worldcover2021.tif   WorldCover class codes over DOWNLOAD_BBOX, EPSG:4326

The landslide labels come from the USGS Landslide Inventories across the United States v3 CSVs,
already unpacked in data/raw/usgs_v3/ (https://doi.org/10.5066/P14AJF8I).

Run from the repo root:
  python ml/scripts/download_region.py [--force]
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.merge import merge
from rasterio.windows import from_bounds

sys.path.insert(0, str(Path(__file__).resolve().parent))
from download_sources import gdal_env  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw"
REGION_DEM_PATH = RAW_DIR / "region_dem_cop30.tif"
REGION_LANDCOVER_PATH = RAW_DIR / "region_landcover_worldcover2021.tif"

# Western and central Cascades around Rainier, [west, south, east, north] in EPSG:4326. The
# Washington Geological Survey lidar and hazard-zonation inventories are dense here; the Rainier
# box sits inside and is held out of training (train_regional_susceptibility.py).
REGION_BBOX = (-122.6, 46.4, -121.2, 47.5)
# Read a margin past the region so slope and flow routing at its edge see real terrain.
DOWNLOAD_MARGIN_DEG = 0.05
DOWNLOAD_BBOX = (REGION_BBOX[0] - DOWNLOAD_MARGIN_DEG, REGION_BBOX[1] - DOWNLOAD_MARGIN_DEG,
                 REGION_BBOX[2] + DOWNLOAD_MARGIN_DEG, REGION_BBOX[3] + DOWNLOAD_MARGIN_DEG)

DEM_URL = ("https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_N{lat:02d}_00_W{lon:03d}_00_DEM/"
           "Copernicus_DSM_COG_10_N{lat:02d}_00_W{lon:03d}_00_DEM.tif")
WORLDCOVER_URL = ("https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
                  "ESA_WorldCover_10m_2021_v200_{tile}_Map.tif")


def rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def dem_tiles(bbox: tuple[float, float, float, float]) -> list[str]:
    """GLO-30 1x1 degree tiles, named by their SW corner, that intersect bbox."""
    west, south, east, north = bbox
    urls = []
    for lat in range(math.floor(south), math.ceil(north)):
        for lon in range(math.floor(west), math.ceil(east)):
            urls.append(DEM_URL.format(lat=lat, lon=-lon))
    return urls


def worldcover_tiles(bbox: tuple[float, float, float, float]) -> list[str]:
    """WorldCover 3x3 degree tiles, named by their SW corner, that intersect bbox."""
    west, south, east, north = bbox
    urls = []
    for lat in range(math.floor(south / 3) * 3, math.ceil(north / 3) * 3, 3):
        for lon in range(math.floor(west / 3) * 3, math.ceil(east / 3) * 3, 3):
            ns, ew = ("N" if lat >= 0 else "S"), ("E" if lon >= 0 else "W")
            urls.append(WORLDCOVER_URL.format(tile=f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}"))
    return urls


def snap_bounds(bbox, transform) -> tuple[float, float, float, float]:
    """bbox grown outward onto the source pixel edges, so the mosaic copies pixels without resampling."""
    west, south, east, north = bbox
    x0, y0, dx, dy = transform.c, transform.f, transform.a, -transform.e
    return (x0 + math.floor(round((west - x0) / dx, 6)) * dx, y0 - math.ceil(round((y0 - south) / dy, 6)) * dy,
            x0 + math.ceil(round((east - x0) / dx, 6)) * dx, y0 - math.floor(round((y0 - north) / dy, 6)) * dy)


def fetch_mosaic(urls: list[str], out_path: Path, bbox, dtype: str, nodata, predictor: int) -> None:
    """Window-read bbox from each remote COG, mosaic, and write a tiled GeoTIFF."""
    with gdal_env():
        sources = [rasterio.open(f"/vsicurl/{url}") for url in urls]
        try:
            res = sources[0].res
            bounds = snap_bounds(bbox, sources[0].transform)
            data, transform = merge(sources, bounds=bounds, res=res, nodata=nodata)
            profile = dict(sources[0].profile)
        finally:
            for src in sources:
                src.close()
    profile.update(driver="GTiff", width=data.shape[2], height=data.shape[1], count=1, dtype=dtype,
                   transform=transform, nodata=nodata, tiled=True, blockxsize=512, blockysize=512,
                   compress="deflate", predictor=predictor, BIGTIFF="IF_SAFER")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    partial = out_path.with_name(out_path.name + ".part")
    with rasterio.open(partial, "w", **profile) as dst:
        dst.write(data[0].astype(dtype), 1)
        dst.update_tags(SOURCE_URLS=" ".join(urls), BBOX=",".join(map(str, bbox)),
                        SOURCE="ml/scripts/download_region.py")
    partial.replace(out_path)


def summarize(path: Path) -> None:
    with rasterio.open(path) as ds:
        b = ds.bounds
        sample = ds.read(1, out_shape=(ds.height // 20, ds.width // 20))
        valid = sample[sample != ds.nodata] if ds.nodata is not None and not np.isnan(ds.nodata) else sample
        print(f"  {rel(path)}: {ds.width} x {ds.height} px, bounds ({b.left:.3f}, {b.bottom:.3f}, "
              f"{b.right:.3f}, {b.top:.3f}), {path.stat().st_size / 1e6:.1f} MB, "
              f"sampled values {np.nanmin(valid):.0f}..{np.nanmax(valid):.0f}")
        window = from_bounds(*DOWNLOAD_BBOX, transform=ds.transform)
        if (window.col_off < -1e-6 or window.row_off < -1e-6 or window.col_off + window.width > ds.width + 1e-6
                or window.row_off + window.height > ds.height + 1e-6):
            raise SystemExit(f"{rel(path)} does not cover {DOWNLOAD_BBOX}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download the regional DEM and land cover windows.")
    parser.add_argument("--force", action="store_true", help="download again even if the files exist")
    args = parser.parse_args()
    print(f"region {REGION_BBOX}, reading {DOWNLOAD_BBOX}")
    stages = (
        (REGION_DEM_PATH, dem_tiles(DOWNLOAD_BBOX), "float32", -32767.0, 3),
        (REGION_LANDCOVER_PATH, worldcover_tiles(DOWNLOAD_BBOX), "uint8", 0, 1),
    )
    for path, urls, dtype, nodata, predictor in stages:
        if path.exists() and not args.force:
            print(f"  {rel(path)} exists, skipping (use --force)")
        else:
            print(f"  reading {len(urls)} tile(s): {', '.join(u.rsplit('/', 1)[-1] for u in urls)}")
            fetch_mosaic(urls, path, DOWNLOAD_BBOX, dtype, nodata, predictor)
        summarize(path)


if __name__ == "__main__":
    main()
