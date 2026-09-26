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

from app.risk import BIN_EDGES, RISK_HEX, RISK_LEVELS, hex_rgb

# backend/tiles/<layer>/{z}/{x}/{y}.png, served by the API at /tiles.
TILES_DIR = Path(__file__).resolve().parents[2] / "tiles"
TILE_SIZE = 256

# Shared facts. EPSG:4326, [west, south, east, north].
RAINIER_BBOX = (-121.93, 46.76, -121.54, 46.96)
# z10 shows the whole mountain; past z14 the map stretches the z14 tiles.
DEFAULT_ZOOMS = range(10, 15)

# A stepped ramp on the shared bins (design addendum, Raster layers), so every color on the map
# is a level word in the panel. Low is transparent so the terrain shows through, and the worst
# ground is the most opaque. Probability and susceptibility share it.
LEVEL_ALPHA = {"low": 0.0, "moderate": 0.40, "high": 0.55, "extreme": 0.70}
LEVEL_RGBA = np.array(
    [[*hex_rgb(RISK_HEX[level]), round(255 * LEVEL_ALPHA[level])] for level in RISK_LEVELS], dtype=np.uint8
)
NO_DATA_INDEX = len(RISK_LEVELS)


def level_indexes(values: np.ndarray) -> np.ndarray:
    """uint8 level index per value: 0 low to 3 extreme, and NO_DATA_INDEX for NaN."""
    missing = np.isnan(values)
    index = np.digitize(np.where(missing, 0.0, values), BIN_EDGES).astype(np.uint8)
    index[missing] = NO_DATA_INDEX
    return index


def colorize(values: np.ndarray) -> np.ndarray:
    """RGBA uint8 for an array of 0-1 values. NaN is fully transparent."""
    rgba = np.zeros(values.shape + (4,), dtype=np.uint8)
    index = level_indexes(values)
    present = index != NO_DATA_INDEX
    rgba[present] = LEVEL_RGBA[index[present]]
    return rgba


# Tiles are 8-bit palette PNGs: one entry per level and a transparent one for no data. They
# encode far faster than RGBA and are a fraction of the size.
PALETTE_RGB = [int(c) for c in LEVEL_RGBA[:, :3].flatten()] + [0, 0, 0]
PALETTE_ALPHA = bytes([int(a) for a in LEVEL_RGBA[:, 3]] + [0])


def palette_image(values: np.ndarray) -> Image.Image:
    """8-bit PNG image of 0-1 values on the stepped risk ramp. NaN is transparent."""
    image = Image.fromarray(level_indexes(values), "P")
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
        # zlib level 6: a tenth of level 9's time for tiles about 9% larger. A run renders these live.
        palette_image(warp_tile(data, src_transform, src_crs, tile)).save(path, compress_level=6)
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
