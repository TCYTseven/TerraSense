"""Ground elevation at points, from the same Terrarium tiles the map drapes its terrain on.

Tiles are read from data/raw/terrarium/{z}/{x}/{y}.png and fetched from the public
AWS bucket when missing, then kept there. Any tile that cannot be had makes the whole
answer None, so a caller never mixes real heights with guesses.
"""

from __future__ import annotations

import io
import math

from app.config import REPO_ROOT

TERRARIUM_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
TILE_DIR = REPO_ROOT / "data" / "raw" / "terrarium"
# About 13 m a pixel at Rainier's latitude, finer than the 80 m the runout samples at.
ZOOM = 13
TILE_PX = 256
FETCH_TIMEOUT_S = 5.0

_tiles: dict[tuple[int, int, int], object] = {}


def sample_elevations(points: list[tuple[float, float]]) -> list[float] | None:
    """Meters above sea level for each (lon, lat), bilinear on the tile grid. None if any tile is missing."""
    try:
        return [_elevation(lon, lat) for lon, lat in points]
    except (OSError, ValueError):
        return None


def _elevation(lon: float, lat: float) -> float:
    scale = 2**ZOOM * TILE_PX
    px = (lon + 180.0) / 360.0 * scale
    lat_rad = math.radians(lat)
    py = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * scale
    # Pixel centers sit at +0.5, so shift before interpolating between the four around the point.
    fx, fy = px - 0.5, py - 0.5
    x0, y0 = math.floor(fx), math.floor(fy)
    tx, ty = fx - x0, fy - y0
    h00 = _pixel(x0, y0)
    h10 = _pixel(x0 + 1, y0)
    h01 = _pixel(x0, y0 + 1)
    h11 = _pixel(x0 + 1, y0 + 1)
    top = h00 * (1 - tx) + h10 * tx
    bottom = h01 * (1 - tx) + h11 * tx
    return top * (1 - ty) + bottom * ty


def _pixel(gx: int, gy: int) -> float:
    tile = _tile(ZOOM, gx // TILE_PX, gy // TILE_PX)
    return float(tile[gy % TILE_PX, gx % TILE_PX])


def _tile(z: int, x: int, y: int):
    key = (z, x, y)
    if key not in _tiles:
        _tiles[key] = _decode(_read(z, x, y))
    return _tiles[key]


def _read(z: int, x: int, y: int) -> bytes:
    path = TILE_DIR / str(z) / str(x) / f"{y}.png"
    if path.exists():
        return path.read_bytes()
    import httpx

    try:
        response = httpx.get(TERRARIUM_URL.format(z=z, x=x, y=y), timeout=FETCH_TIMEOUT_S)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise OSError(f"Terrarium tile {z}/{x}/{y} unavailable") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    return response.content


def _decode(data: bytes):
    import numpy as np
    from PIL import Image

    rgb = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"), dtype="float64")
    # Terrarium: height = R * 256 + G + B / 256 - 32768.
    return rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768
