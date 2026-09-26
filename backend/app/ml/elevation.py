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
    px, py = _pixel_xy(lon, lat)
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


class Grid:
    """Heights on a Web Mercator pixel grid, `factor` z13 pixels to a cell (block mean)."""

    def __init__(self, heights, col0: int, row0: int, factor: int) -> None:
        self.heights = heights
        self.col0 = col0
        self.row0 = row0
        self.factor = factor

    def cell_m(self, lat: float) -> float:
        """Ground size of one cell at this latitude."""
        return 2 * math.pi * 6378137.0 * math.cos(math.radians(lat)) / (2**ZOOM * TILE_PX) * self.factor

    def cell_of(self, lon: float, lat: float) -> tuple[int, int]:
        px, py = _pixel_xy(lon, lat)
        return int(py // self.factor) - self.row0, int(px // self.factor) - self.col0

    def lonlat(self, row: float, col: float) -> tuple[float, float]:
        """The lon/lat of a fractional cell position; (row, col) = (0, 0) is the grid's top-left corner."""
        return _lonlat((col + self.col0) * self.factor, (row + self.row0) * self.factor)


def height_grid(lon: float, lat: float, radius_m: float, factor: int = 2) -> Grid | None:
    """A square of heights centered on (lon, lat). None if any tile is unavailable."""
    import numpy as np

    px, py = _pixel_xy(lon, lat)
    pixel_m = 2 * math.pi * 6378137.0 * math.cos(math.radians(lat)) / (2**ZOOM * TILE_PX)
    reach = int(radius_m / pixel_m)
    col0, row0 = int((px - reach) // factor), int((py - reach) // factor)
    size = 2 * reach // factor
    x_start, y_start = col0 * factor, row0 * factor
    span = size * factor
    try:
        raw = np.empty((span, span), dtype="float64")
        for ty in range(y_start // TILE_PX, (y_start + span - 1) // TILE_PX + 1):
            for tx in range(x_start // TILE_PX, (x_start + span - 1) // TILE_PX + 1):
                tile = _tile(ZOOM, tx, ty)
                gx0, gy0 = max(x_start, tx * TILE_PX), max(y_start, ty * TILE_PX)
                gx1, gy1 = min(x_start + span, (tx + 1) * TILE_PX), min(y_start + span, (ty + 1) * TILE_PX)
                raw[gy0 - y_start : gy1 - y_start, gx0 - x_start : gx1 - x_start] = tile[
                    gy0 - ty * TILE_PX : gy1 - ty * TILE_PX, gx0 - tx * TILE_PX : gx1 - tx * TILE_PX
                ]
    except (OSError, ValueError):
        return None
    heights = raw.reshape(size, factor, size, factor).mean(axis=(1, 3))
    return Grid(heights, col0, row0, factor)


def _pixel_xy(lon: float, lat: float) -> tuple[float, float]:
    scale = 2**ZOOM * TILE_PX
    px = (lon + 180.0) / 360.0 * scale
    py = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * scale
    return px, py


def _lonlat(px: float, py: float) -> tuple[float, float]:
    scale = 2**ZOOM * TILE_PX
    lon = px / scale * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * py / scale))))
    return lon, lat
