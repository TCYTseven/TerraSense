"""Where the 72-hour map puts the hero trail in danger (step 18).

From one probability map:

- segment_risks(): each hero trail segment's probability: the worst cell the tread crosses.
- flagged_run(): the worst segment, grown along the trail while its neighbors stay at high or
  above. This is the mile range the ranger alert closes and the bypass avoids (step 19).
- hazard_zone(): the high ground within CORRIDOR_M of the flagged miles that connects to them,
  as one polygon, with the terrain under it from the step 11 feature stack.

The zone is the worst cluster the hero trail crosses, not the worst anywhere in the box:
hikers are the audience, and a cluster that no trail meets is not a trail hazard.
Keep this module free of API and database imports, like the tiler.
"""

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import rasterio
import shapely
from rasterio.features import geometry_mask, shapes
from rasterio.warp import transform as warp_transform
from rasterio.warp import transform_geom
from rasterio.windows import Window, from_bounds
from shapely.geometry import mapping, shape

from app.config import REPO_ROOT
from app.ml.probability import ProbabilityMap
from app.risk import HIGH_THRESHOLD, RiskLevel, risk_level

FEATURES_PATH = REPO_ROOT / "data" / "processed" / "features.tif"
FEATURE_BANDS = ("elevation", "slope", "aspect", "curvature", "dist_drainage", "landcover", "twi")

SAMPLE_STEP_M = 10  # spacing of the samples along a segment, a third of a cell
CORRIDOR_M = 250  # how far from the flagged miles the zone may reach
TOUCH_M = 45  # a high cluster this close to the flagged line belongs to the zone
SIMPLIFY_M = 15  # outline smoothing: half a cell, so the pixel staircase goes away
NEAR_CHANNEL_M = 100  # "near a drainage": within this distance of a D8 channel

# ESA WorldCover 2021 classes, as the step 10 download names them.
WORLDCOVER_CLASSES = {
    10: "Tree cover",
    20: "Shrubland",
    30: "Grassland",
    40: "Cropland",
    50: "Built-up",
    60: "Bare/sparse vegetation",
    70: "Snow and ice",
    80: "Permanent water bodies",
    90: "Herbaceous wetland",
    95: "Mangroves",
    100: "Moss and lichen",
}
# Thin or no cover: bare ground, moss and lichen, grass, and glacier margins.
SPARSE_COVER = {30, 60, 70, 100}

COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")

# Driver names the Terrain Analyst may cite. The hints below pick from the terrain ones.
TERRAIN_DRIVERS = ("slope_angle", "drainage_proximity", "sparse_vegetation", "soil_wetness", "concave_hollow")


@dataclass(frozen=True)
class SegmentLine:
    """A hero trail segment as the database holds it."""

    id: str
    seq: int
    start_mile: float
    end_mile: float
    coordinates: list[list[float]]  # [lon, lat]


@dataclass(frozen=True)
class SegmentRisk:
    id: str
    seq: int
    start_mile: float
    end_mile: float
    probability: float
    level: RiskLevel


@dataclass(frozen=True)
class FlaggedRun:
    """The contiguous miles around the worst segment that sit at high or above."""

    start_mile: float
    end_mile: float
    seqs: tuple[int, ...]
    max_probability: float
    level: RiskLevel


@dataclass(frozen=True)
class HazardZone:
    polygon: dict  # GeoJSON Polygon, [lon, lat]
    area_km2: float
    cells: int
    max_probability: float
    mean_probability: float
    level: RiskLevel
    centroid: tuple[float, float]  # lon, lat
    terrain: dict | None  # stats under the zone, None without the step 11 stack
    type_hint: str  # "debris_flow" or "landslide"
    drivers_hint: tuple[str, ...]


def _grid_xy(coordinates: list[list[float]], crs: str) -> np.ndarray:
    """[lon, lat] vertices to the probability grid's CRS."""
    lons, lats = zip(*[(c[0], c[1]) for c in coordinates], strict=True)
    xs, ys = warp_transform("EPSG:4326", crs, list(lons), list(lats))
    return np.column_stack([xs, ys])


def sample_max(probability: ProbabilityMap, coordinates: list[list[float]]) -> float:
    """The worst probability along a [lon, lat, ...] line, sampled every SAMPLE_STEP_M. 0 off the grid."""
    values = probability.values
    line = shapely.LineString(_grid_xy(coordinates, probability.crs))
    count = max(2, math.ceil(line.length / SAMPLE_STEP_M) + 1)
    points = shapely.get_coordinates(shapely.line_interpolate_point(line, np.linspace(0, line.length, count)))
    cols, rows = ~probability.transform * (points[:, 0], points[:, 1])
    cols, rows = np.floor(cols).astype(int), np.floor(rows).astype(int)
    inside = (rows >= 0) & (rows < values.shape[0]) & (cols >= 0) & (cols < values.shape[1])
    if not inside.any():
        return 0.0
    worst = float(np.nanmax(values[rows[inside], cols[inside]], initial=0.0))
    return round(min(max(worst, 0.0), 1.0), 3)


def segment_risks(probability: ProbabilityMap, segments: list[SegmentLine]) -> list[SegmentRisk]:
    """Each segment's probability and level, in trail order."""
    risks = []
    for segment in sorted(segments, key=lambda s: s.seq):
        value = sample_max(probability, segment.coordinates)
        risks.append(SegmentRisk(segment.id, segment.seq, segment.start_mile, segment.end_mile, value, risk_level(value)))
    return risks


def flagged_run(risks: list[SegmentRisk], threshold: float = HIGH_THRESHOLD) -> FlaggedRun | None:
    """The worst segment and its neighbors at or above the threshold. None when no segment gets there.

    The loop's trailhead is a break: a run does not wrap from the last mile to mile 0.
    """
    if not risks:
        return None
    worst = max(range(len(risks)), key=lambda i: risks[i].probability)
    if risks[worst].probability < threshold:
        return None
    low, high = worst, worst
    while low > 0 and risks[low - 1].probability >= threshold:
        low -= 1
    while high < len(risks) - 1 and risks[high + 1].probability >= threshold:
        high += 1
    run = risks[low:high + 1]
    peak = max(r.probability for r in run)
    return FlaggedRun(
        start_mile=run[0].start_mile,
        end_mile=run[-1].end_mile,
        seqs=tuple(r.seq for r in run),
        max_probability=peak,
        level=risk_level(peak),
    )


def _window_around(geometry, probability: ProbabilityMap) -> Window:
    rows, cols = probability.values.shape
    window = from_bounds(*geometry.bounds, transform=probability.transform)
    col0 = max(0, math.floor(window.col_off))
    row0 = max(0, math.floor(window.row_off))
    col1 = min(cols, math.ceil(window.col_off + window.width))
    row1 = min(rows, math.ceil(window.row_off + window.height))
    return Window(col0, row0, max(0, col1 - col0), max(0, row1 - row0))


def _one_polygon(geometry, near) -> shapely.Polygon:
    """A single outer ring: the part of a multipolygon nearest `near` (largest on a tie), no holes."""
    parts = list(shapely.get_parts(geometry))
    part = min(parts, key=lambda p: (round(p.distance(near), 1), -p.area))
    return shapely.Polygon(part.exterior)


def hazard_zone(probability: ProbabilityMap, flagged: list[SegmentLine],
                features_path: Path = FEATURES_PATH) -> HazardZone | None:
    """The high ground around the flagged segments, as one polygon with its terrain."""
    if not flagged:
        return None
    line = shapely.union_all([shapely.LineString(_grid_xy(s.coordinates, probability.crs)) for s in flagged])
    corridor = line.buffer(CORRIDOR_M)
    window = _window_around(corridor, probability)
    if window.width == 0 or window.height == 0:
        return None
    values = probability.values[window.row_off:window.row_off + window.height,
                                window.col_off:window.col_off + window.width]
    transform = rasterio.windows.transform(window, probability.transform)
    in_corridor = geometry_mask([mapping(corridor)], out_shape=values.shape, transform=transform, invert=True)
    high = in_corridor & (np.nan_to_num(values, nan=0.0) >= HIGH_THRESHOLD)
    if not high.any():
        return None

    # Connected pieces of high ground (8-connected), as pixel-edge polygons.
    pieces = [shape(geom) for geom, _ in shapes(high.astype("uint8"), mask=high, transform=transform, connectivity=8)]
    touching = [p for p in pieces if p.distance(line) <= TOUCH_M]
    if not touching:
        return None
    exact = _one_polygon(shapely.union_all(touching), line)

    cells = geometry_mask([mapping(exact)], out_shape=values.shape, transform=transform, invert=True) & high
    zone_values = values[cells]
    outline = exact.simplify(SIMPLIFY_M, preserve_topology=True)
    outline = shapely.Polygon(outline.exterior) if outline.is_valid and not outline.is_empty else exact
    polygon = transform_geom(probability.crs, "EPSG:4326", mapping(outline))
    polygon = {
        "type": "Polygon",
        "coordinates": [[[round(x, 6), round(y, 6)] for x, y in ring] for ring in polygon["coordinates"]],
    }
    center = exact.representative_point()
    (lon,), (lat,) = warp_transform(probability.crs, "EPSG:4326", [center.x], [center.y])

    terrain = _terrain(features_path, probability, window, cells)
    type_hint, drivers = _hints(terrain)
    peak = round(float(zone_values.max()), 3)
    return HazardZone(
        polygon=polygon,
        area_km2=round(float(exact.area) / 1e6, 3),
        cells=int(cells.sum()),
        max_probability=peak,
        mean_probability=round(float(zone_values.mean()), 3),
        level=risk_level(peak),
        centroid=(round(lon, 5), round(lat, 5)),
        terrain=terrain,
        type_hint=type_hint,
        drivers_hint=drivers,
    )


@lru_cache(maxsize=2)
def _stack(path: Path, mtime_ns: int) -> tuple[np.ndarray, dict]:
    """The step 11 feature stack and the box medians the zone is compared against."""
    with rasterio.open(path) as src:
        if tuple(src.descriptions) != FEATURE_BANDS:
            raise ValueError(f"{path} bands {src.descriptions} are not {FEATURE_BANDS}")
        data = src.read().astype("float32")
    band = dict(zip(FEATURE_BANDS, data, strict=True))
    box = {
        "slope_deg_median": round(float(np.nanmedian(band["slope"])), 1),
        "dist_drainage_m_median": round(float(np.nanmedian(band["dist_drainage"])), 0),
        "twi_median": round(float(np.nanmedian(band["twi"])), 2),
        "twi_p75": round(float(np.nanpercentile(band["twi"], 75)), 2),
    }
    return data, box


def _terrain(path: Path, probability: ProbabilityMap, window: Window, cells: np.ndarray) -> dict | None:
    """Terrain stats under the zone. None when the stack is missing or on another grid."""
    if not path.exists():
        return None
    data, box = _stack(path, path.stat().st_mtime_ns)
    if data.shape[1:] != probability.values.shape:
        return None
    sub = data[:, window.row_off:window.row_off + window.height, window.col_off:window.col_off + window.width]
    band = {name: sub[i][cells] for i, name in enumerate(FEATURE_BANDS)}

    aspect = band["aspect"][~np.isnan(band["aspect"])]
    facing = None
    if aspect.size:
        radians = np.radians(aspect)
        mean = math.degrees(math.atan2(np.sin(radians).mean(), np.cos(radians).mean())) % 360
        facing = COMPASS[int((mean + 22.5) // 45) % 8]
    codes, counts = np.unique(band["landcover"][~np.isnan(band["landcover"])].astype(int), return_counts=True)
    order = np.argsort(counts)[::-1][:3]
    cover = {WORLDCOVER_CLASSES.get(int(codes[i]), f"class {codes[i]}"): round(float(counts[i] / counts.sum()), 2)
             for i in order}
    sparse = float(sum(counts[i] for i, c in enumerate(codes) if c in SPARSE_COVER) / max(counts.sum(), 1))
    return {
        "elevation_m": {"min": round(float(np.nanmin(band["elevation"]))), "max": round(float(np.nanmax(band["elevation"])))},
        "slope_deg": {"mean": round(float(np.nanmean(band["slope"])), 1),
                      "p90": round(float(np.nanpercentile(band["slope"], 90)), 1)},
        "facing": facing,
        "curvature_mean": round(float(np.nanmean(band["curvature"])), 2),
        "dist_drainage_m_median": round(float(np.nanmedian(band["dist_drainage"]))),
        "share_near_channel": round(float(np.mean(band["dist_drainage"] <= NEAR_CHANNEL_M)), 2),
        "land_cover": cover,
        "share_sparse_cover": round(sparse, 2),
        "twi_mean": round(float(np.nanmean(band["twi"])), 2),
        "box": box,
    }


def _hints(terrain: dict | None) -> tuple[str, tuple[str, ...]]:
    """A hazard type and the terrain drivers the stats support. The Terrain Analyst decides."""
    if terrain is None:
        return "landslide", ()
    box = terrain["box"]
    drivers = []
    if terrain["slope_deg"]["mean"] >= 30 or terrain["slope_deg"]["mean"] >= box["slope_deg_median"] + 8:
        drivers.append("slope_angle")
    if terrain["share_near_channel"] >= 0.4:
        drivers.append("drainage_proximity")
    if terrain["share_sparse_cover"] >= 0.5:
        drivers.append("sparse_vegetation")
    if terrain["twi_mean"] >= box["twi_p75"]:
        drivers.append("soil_wetness")
    if terrain["curvature_mean"] <= -0.2:
        drivers.append("concave_hollow")
    channelized = terrain["share_near_channel"] >= 0.5 or terrain["curvature_mean"] <= -0.2
    return ("debris_flow" if channelized else "landslide"), tuple(drivers)
