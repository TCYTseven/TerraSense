"""XYZ map tiles in Web Mercator (EPSG:3857) from a single-band 0-1 raster.

ml/scripts/render_tiles.py uses this offline for susceptibility (step 13), and the API uses it
live for the 72-hour probability layer (step 18), so both layers sit on the terrain the same way.
Keep this module free of API and database imports: the ML scripts import it too.
"""

import json
import shutil
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

import mercantile
import numpy as np
import rasterio
from affine import Affine
from PIL import Image
from rasterio.crs import CRS
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, reproject

# backend/tiles/<layer>/{z}/{x}/{y}.png, served by the API at /tiles.
TILES_DIR = Path(__file__).resolve().parents[2] / "tiles"
TILE_SIZE = 256

# Shared facts. EPSG:4326, [west, south, east, north].
RAINIER_BBOX = (-121.93, 46.76, -121.54, 46.96)
# z10 shows the whole mountain; past z14 the map stretches the z14 tiles.
DEFAULT_ZOOMS = range(10, 15)

# Risk ramp at the shared bin edges: low < 0.2 < moderate < 0.45 < high < 0.7 < extreme.
RAMP_STOPS = np.array([0.0, 0.2, 0.45, 0.7, 1.0])
RAMP_RGB = np.array([[34, 197, 94], [34, 197, 94], [245, 158, 11], [249, 115, 22], [239, 68, 68]])
# Low values fade out so the terrain shows through. The worst ground is the most opaque.
RAMP_ALPHA = np.array([0, 60, 150, 200, 225])


def colorize(values: np.ndarray) -> np.ndarray:
    """RGBA uint8 for an array of 0-1 values. NaN is fully transparent."""
    missing = np.isnan(values)
    clean = np.where(missing, 0.0, np.clip(values, 0, 1))
    rgba = np.empty(values.shape + (4,), dtype=np.uint8)
    for channel in range(3):
        rgba[..., channel] = np.interp(clean, RAMP_STOPS, RAMP_RGB[:, channel])
    rgba[..., 3] = np.interp(clean, RAMP_STOPS, RAMP_ALPHA)
    rgba[missing, 3] = 0
    return rgba


# Tiles are 8-bit palette PNGs: 64 value levels look like a smooth ramp, encode 20x faster
# than optimized RGBA, and are a third the size. The last palette entry is transparent (no data).
LEVELS = 64
_LEVEL_RGBA = colorize(np.linspace(0, 1, LEVELS)[None, :])[0]
PALETTE_RGB = [int(c) for c in _LEVEL_RGBA[:, :3].flatten()] + [0, 0, 0]
PALETTE_ALPHA = bytes([int(a) for a in _LEVEL_RGBA[:, 3]] + [0])


def palette_image(values: np.ndarray) -> Image.Image:
    """8-bit PNG image of 0-1 values on the risk ramp. NaN is transparent."""
    index = np.full(values.shape, LEVELS, dtype=np.uint8)
    present = ~np.isnan(values)
    index[present] = np.rint(np.clip(values[present], 0, 1) * (LEVELS - 1)).astype(np.uint8)
    image = Image.fromarray(index, "P")
    image.putpalette(PALETTE_RGB)
    image.info["transparency"] = PALETTE_ALPHA
    return image


def warp_tile(data: np.ndarray, src_transform: Affine, src_crs: CRS, tile: mercantile.Tile) -> np.ndarray:
    """The raster resampled onto one 256 x 256 Web Mercator tile. NaN where there is no data."""
    left, bottom, right, top = mercantile.xy_bounds(tile)
    out = np.full((TILE_SIZE, TILE_SIZE), np.nan, dtype="float32")
    reproject(
        source=data,
        destination=out,
        src_transform=src_transform,
        src_crs=src_crs,
        src_nodata=np.nan,
        dst_transform=from_bounds(left, bottom, right, top, TILE_SIZE, TILE_SIZE),
        dst_crs="EPSG:3857",
        dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )
    return out


def render_xyz(raster: Path, layer: str, zooms: Iterable[int] = DEFAULT_ZOOMS,
               bbox: tuple[float, float, float, float] = RAINIER_BBOX, tiles_dir: Path = TILES_DIR) -> dict:
    """Write tiles_dir/<layer>/{z}/{x}/{y}.png for every tile touching bbox, plus metadata.json.

    Renders into a temporary folder and swaps it in, so the API never serves a half-written layer.
    """
    zooms = list(zooms)
    with rasterio.open(raster) as src:
        data, src_transform, src_crs = src.read(1), src.transform, src.crs
        method = src.tags().get("METHOD")

    final_dir = tiles_dir / layer
    work_dir = tiles_dir / f".{layer}.rendering"
    shutil.rmtree(work_dir, ignore_errors=True)
    count = 0
    for tile in mercantile.tiles(*bbox, zooms=zooms):
        path = work_dir / str(tile.z) / str(tile.x) / f"{tile.y}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        palette_image(warp_tile(data, src_transform, src_crs, tile)).save(path, compress_level=9)
        count += 1

    created = datetime.now(UTC)
    metadata = {
        "layer": layer,
        "bounds": list(bbox),
        "minzoom": min(zooms),
        "maxzoom": max(zooms),
        "tile_count": count,
        "method": method,
        "source": raster.name,
        "version": created.strftime("%Y%m%dT%H%M%S%fZ"),
        "created_at": created.isoformat(timespec="seconds"),
    }
    (work_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")

    old_dir = tiles_dir / f".{layer}.old"
    shutil.rmtree(old_dir, ignore_errors=True)
    if final_dir.exists():
        final_dir.rename(old_dir)
    work_dir.rename(final_dir)
    shutil.rmtree(old_dir, ignore_errors=True)
    return metadata


def read_metadata(layer: str, tiles_dir: Path = TILES_DIR) -> dict | None:
    """The metadata.json of a rendered layer, or None if it has not been rendered."""
    path = tiles_dir / layer / "metadata.json"
    return json.loads(path.read_text()) if path.exists() else None
