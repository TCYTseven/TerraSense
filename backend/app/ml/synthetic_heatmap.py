"""Procedural susceptibility-style values for catalog peaks, matching frontend/lib/synthetic-heatmap.ts.

Tiles use the same palette as app/ml/tiles.py so static mountains drape like Rainier.
"""

from __future__ import annotations

import io
import math
import struct
from dataclasses import dataclass
from typing import Callable

import mercantile
import numpy as np

from app.ml.tiles import DEFAULT_ZOOMS, TILE_SIZE, palette_image

KM_PER_DEG = 111.32
FOOTPRINT_PER_M = 0.85 / math.tan(math.radians(22))
FOOTPRINT_KM_MIN = 3.0
FOOTPRINT_KM_MAX = 25.0
SYNTHETIC_METHOD = "seeded synthetic susceptibility"


def _hash_seed(*parts: str | float) -> int:
    h = 2166136261
    for part in parts:
        for char in str(part):
            h ^= ord(char)
            h = (h * 16777619) & 0xFFFFFFFF
    return h


def _mulberry32(seed: int) -> Callable[[], float]:
    state = seed & 0xFFFFFFFF

    def draw() -> float:
        nonlocal state
        state = (state + 0x6D2B79F5) & 0xFFFFFFFF
        t = ((state ^ (state >> 15)) * (1 | state)) & 0xFFFFFFFF
        t = (t + ((t ^ (t >> 7)) * (61 | t))) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296

    return draw


def _smoothstep(edge0: float, edge1: float, x: float) -> float:
    if edge1 == edge0:
        return 0.0
    t = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3 - 2 * t)


@dataclass
class _NoiseGrid:
    size: int
    values: np.ndarray


def _make_grid(rand: Callable[[], float], size: int) -> _NoiseGrid:
    base = np.array([rand() for _ in range(size * size)], dtype=np.float64)
    values = np.zeros((size + 1) * (size + 1), dtype=np.float64)
    for yy in range(size + 1):
        for xx in range(size + 1):
            values[yy * (size + 1) + xx] = base[(yy % size) * size + (xx % size)]
    return _NoiseGrid(size=size, values=values)


def _sample_grid(grid: _NoiseGrid, x: float, y: float) -> float:
    size = grid.size
    span = float(size)
    fx = ((x % span) + span) % span
    fy = ((y % span) + span) % span
    x0 = int(math.floor(fx))
    y0 = int(math.floor(fy))
    x1 = (x0 + 1) % (size + 1)
    y1 = (y0 + 1) % (size + 1)
    tx = fx - x0
    ty = fy - y0
    sx = tx * tx * (3 - 2 * tx)
    sy = ty * ty * (3 - 2 * ty)
    values = grid.values

    def at(yy: int, xx: int) -> float:
        return float(values[yy * (size + 1) + xx])

    top = at(y0, x0) + (at(y0, x1) - at(y0, x0)) * sx
    bottom = at(y1, x0) + (at(y1, x1) - at(y1, x0)) * sx
    return top + (bottom - top) * sy


@dataclass
class _Octave:
    grid: _NoiseGrid
    freq: float
    weight: float
    ox: float
    oy: float
    angle: float


@dataclass
class _Hotspot:
    x: float
    y: float
    sigma: float
    amp: float


@dataclass
class _Field:
    octaves: list[_Octave]
    spots: list[_Hotspot]
    cover: float
    contrast: float


def _fbm(nx: float, ny: float, octaves: list[_Octave]) -> float:
    noise = 0.0
    weight = 0.0
    for octave in octaves:
        cos_a = math.cos(octave.angle)
        sin_a = math.sin(octave.angle)
        rx = nx * cos_a - ny * sin_a
        ry = nx * sin_a + ny * cos_a
        noise += octave.weight * _sample_grid(octave.grid, rx * octave.freq + octave.ox, ry * octave.freq + octave.oy)
        weight += octave.weight
    return noise / weight if weight else 0.0


def _build_field(rand: Callable[[], float]) -> _Field:
    octaves: list[_Octave] = []
    freq = 1.4 + rand() * 2.2
    for _ in range(4):
        octaves.append(
            _Octave(
                grid=_make_grid(rand, 4 + int(rand() * 5)),
                freq=freq,
                weight=1 / freq,
                ox=rand() * 40,
                oy=rand() * 40,
                angle=rand() * math.pi * 2,
            )
        )
        freq *= 1.85 + rand() * 0.5

    spots = [
        _Hotspot(
            x=(rand() - 0.5) * 0.35,
            y=(rand() - 0.5) * 0.35,
            sigma=0.22 + rand() * 0.2,
            amp=0.55 + rand() * 0.45,
        )
    ]
    for _ in range(2 + int(rand() * 4)):
        spots.append(
            _Hotspot(
                x=(rand() - 0.5) * 1.4,
                y=(rand() - 0.5) * 1.1,
                sigma=0.1 + rand() * 0.22,
                amp=0.25 + rand() * 0.7,
            )
        )
    return _Field(octaves=octaves, spots=spots, cover=0.42 + rand() * 0.28, contrast=0.28 + rand() * 0.34)


def _score_at(nx: float, ny: float, field: _Field) -> float:
    warp_x = _fbm(nx * 0.65 + 3.1, ny * 0.65 - 1.7, field.octaves)
    warp_y = _fbm(nx * 0.65 - 2.4, ny * 0.65 + 4.2, field.octaves)
    wx = nx + (warp_x - 0.5) * 0.5
    wy = ny + (warp_y - 0.5) * 0.5
    noise = _fbm(wx, wy, field.octaves)
    hot = 0.0
    for spot in field.spots:
        distance = math.hypot(nx - spot.x, ny - spot.y)
        hot += spot.amp * math.exp(-(distance * distance) / (2 * spot.sigma * spot.sigma))
    score = field.cover + (noise - 0.5) * field.contrast + min(hot, 1.2) * 0.34
    return max(0.0, min(1.0, score))


def _edge_mask(u: float, v: float) -> float:
    sides = min(_smoothstep(0, 0.14, u), _smoothstep(0, 0.14, 1 - u))
    top = _smoothstep(0, 0.12, v)
    bottom = 1 - _smoothstep(0.62, 1, v)
    radius = math.hypot((u - 0.5) * 2, (v - 0.42) * 2)
    round_edge = 1 - _smoothstep(0.95, 1.35, radius)
    return sides * top * bottom * round_edge


def mountain_footprint_bbox(lon: float, lat: float, elevation_m: int | None) -> tuple[float, float, float, float]:
    """West, south, east, north — same footprint idea as frontend openingBounds without trail points."""
    elev = elevation_m if elevation_m and elevation_m > 0 else 3000
    radius_km = min(FOOTPRINT_KM_MAX, max(FOOTPRINT_KM_MIN, FOOTPRINT_PER_M * elev / 1000))
    km_lon = KM_PER_DEG * math.cos(math.radians(lat))
    d_lat = radius_km / KM_PER_DEG
    d_lon = radius_km / km_lon
    return (lon - d_lon, lat - d_lat, lon + d_lon, lat + d_lat)


def synthetic_version(slug: str) -> str:
    """Stable cache-buster for one peak's procedural tiles."""
    digest = struct.pack(">I", _hash_seed(slug))
    return digest.hex()


def synthetic_layer_metadata(slug: str, lon: float, lat: float, elevation_m: int | None) -> dict:
    """LayerTiles metadata for GET /mountains/{slug}/layers/susceptibility on catalog peaks."""
    bounds = mountain_footprint_bbox(lon, lat, elevation_m)
    zooms = list(DEFAULT_ZOOMS)
    return {
        "layer": "susceptibility",
        "bounds": list(bounds),
        "minzoom": min(zooms),
        "maxzoom": max(zooms),
        "method": SYNTHETIC_METHOD,
        "version": synthetic_version(slug),
        "created_at": "1970-01-01T00:00:00+00:00",
    }


def _field_for_peak(slug: str, lon: float, lat: float) -> _Field:
    rand = _mulberry32(_hash_seed(slug, f"{lon:.4f}", f"{lat:.4f}"))
    return _build_field(rand)


def render_synthetic_tile(
    slug: str,
    lon: float,
    lat: float,
    elevation_m: int | None,
    z: int,
    x: int,
    y: int,
) -> bytes:
    """One 256×256 PNG on the shared risk palette, for /tiles/synthetic/{slug}/{z}/{x}/{y}.png."""
    west, south, east, north = mountain_footprint_bbox(lon, lat, elevation_m)
    bounds = mercantile.bounds(x, y, z)
    field = _field_for_peak(slug, lon, lat)

    lons = np.linspace(bounds.west, bounds.east, TILE_SIZE, dtype=np.float64)
    lats = np.linspace(bounds.north, bounds.south, TILE_SIZE, dtype=np.float64)
    lon_grid, lat_grid = np.meshgrid(lons, lats)

    u = (lon_grid - west) / (east - west)
    v = (north - lat_grid) / (north - south)
    nx = u * 2 - 1
    ny = v * 2 - 1

    scores = np.full((TILE_SIZE, TILE_SIZE), np.nan, dtype=np.float32)
    inside = (u >= 0) & (u <= 1) & (v >= 0) & (v <= 1)
    for row in range(TILE_SIZE):
        for col in range(TILE_SIZE):
            if not inside[row, col]:
                continue
            mask = _edge_mask(float(u[row, col]), float(v[row, col]))
            if mask <= 0:
                continue
            scores[row, col] = _score_at(float(nx[row, col]), float(ny[row, col]), field)

    image = palette_image(scores)
    buf = io.BytesIO()
    image.save(buf, format="PNG", compress_level=6)
    return buf.getvalue()
