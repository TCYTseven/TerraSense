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
RAINIER_SLUG = "mount-rainier"
# z10 shows the whole mountain; past z14 the map stretches the z14 tiles.
DEFAULT_ZOOMS = range(10, 15)
KM_PER_DEG_LAT = 111.32
EARTH_RADIUS_KM = 6371.0
# Soft edge so the drape reads round on the ground, not like a clipped square.
RADIAL_FADE_KM = 2.5


def slug_tiles_dir(slug: str) -> Path:
    """Where one mountain's layers live. Rainier's predate the packs and stay at the root."""
    return TILES_DIR if slug == RAINIER_SLUG else TILES_DIR / slug


def layer_url_path(slug: str, layer: str) -> str:
    """The layer's path under the /tiles static mount, mirroring slug_tiles_dir."""
    return layer if slug == RAINIER_SLUG else f"{slug}/{layer}"

# A stepped ramp on the shared bins (design addendum, Raster layers), so every color on the map
# is a level word in the panel. Low uses a pale wash so steep summit ice still reads on the drape;
# moderate and above stay stronger. Probability and susceptibility share it.
LEVEL_ALPHA = {"low": 0.26, "moderate": 0.40, "high": 0.55, "extreme": 0.70}
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


def lift_for_map_display(values: np.ndarray) -> np.ndarray:
    """Keep scored cells visible on the map; panel thresholds are unchanged."""
    out = values.copy()
    scored = ~np.isnan(out)
    out[scored] = np.maximum(out[scored], 0.06)
    return out


def palette_image(values: np.ndarray) -> Image.Image:
    """8-bit PNG image of 0-1 values on the stepped risk ramp. NaN is transparent."""
    image = Image.fromarray(level_indexes(lift_for_map_display(values)), "P")
    image.putpalette(PALETTE_RGB)
    image.info["transparency"] = PALETTE_ALPHA
    return image


def bbox_circle_radius_km(bbox: tuple[float, float, float, float]) -> tuple[float, float, float]:
    """Center and inscribed radius (km) for a circular mask inside a WGS84 bbox."""
    west, south, east, north = bbox
    center_lon = (west + east) / 2
    center_lat = (south + north) / 2
    km_per_deg_lon = KM_PER_DEG_LAT * np.cos(np.radians(center_lat))
    half_ew = (east - west) * km_per_deg_lon / 2
    half_ns = (north - south) * KM_PER_DEG_LAT / 2
    return center_lon, center_lat, float(min(half_ew, half_ns))


def distance_km(center_lon: float, center_lat: float, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """Great-circle distance in km from one point to arrays of lon/lat."""
    clat = np.radians(center_lat)
    lat_r = np.radians(lat)
    dlat = np.radians(lat - center_lat)
    dlon = np.radians(lon - center_lon)
    a = np.sin(dlat / 2) ** 2 + np.cos(clat) * np.cos(lat_r) * np.sin(dlon / 2) ** 2
    return EARTH_RADIUS_KM * 2 * np.arcsin(np.sqrt(a))


def apply_radial_fade(
    values: np.ndarray,
    tile: mercantile.Tile,
    center_lon: float,
    center_lat: float,
    radius_km: float,
    fade_km: float = RADIAL_FADE_KM,
) -> np.ndarray:
    """Feather heat to transparent outside a circle on the ground (not the bbox square)."""
    height, width = values.shape
    west, south, east, north = mercantile.bounds(tile)
    cols = (np.arange(width, dtype=np.float64) + 0.5) / width
    rows = (np.arange(height, dtype=np.float64) + 0.5) / height
    lons = west + cols * (east - west)
    lats = north - rows[:, np.newaxis] * (north - south)
    lon_grid = np.broadcast_to(lons, (height, width))
    dist = distance_km(center_lon, center_lat, lon_grid, lats)
    out = values.copy()
    out[dist >= radius_km] = np.nan
    if fade_km > 0:
        ring = (dist > radius_km - fade_km) & (dist < radius_km) & ~np.isnan(out)
        taper = np.clip((radius_km - dist) / fade_km, 0.0, 1.0)
        out[ring] *= taper[ring]
    return out


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

    center_lon, center_lat, radius_km = bbox_circle_radius_km(bbox)

    final_dir = tiles_dir / layer
    work_dir = tiles_dir / f".{layer}.rendering"
    shutil.rmtree(work_dir, ignore_errors=True)
    count = 0
    for tile in mercantile.tiles(*bbox, zooms=zooms):
        path = work_dir / str(tile.z) / str(tile.x) / f"{tile.y}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        # zlib level 6: a tenth of level 9's time for tiles about 9% larger. A run renders these live.
        warped = warp_tile(data, src_transform, src_crs, tile)
        warped = apply_radial_fade(warped, tile, center_lon, center_lat, radius_km)
        palette_image(warped).save(path, compress_level=6)
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
