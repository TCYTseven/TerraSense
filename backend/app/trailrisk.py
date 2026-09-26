"""The hill card's trail list: the five most exposed trails on the current map, with why.

GET /mountains/{slug}/trail-risk answers from the probability map the last run published
(ml/artifacts/probability.tif). Before any run it scores a preview on the current rain, the
same way a run would, and says so in `source`. Every number comes from the map and the step 11
terrain stack: nothing here is a model's text or a hand-typed score.

- The trails are ranked the way the advisory's "avoid" shortlist is (trailscan.most_exposed).
- A trail's score is the worst probability on its tread, and the marker sits on that point.
- Its slope and primary factor are read off the terrain stack at that point.
- The overall score is the mean of the five trails' scores.
- The preventative measures are one line per trail, chosen by that trail's primary factor.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import psycopg
import rasterio
from psycopg.rows import dict_row
from rasterio.warp import transform as warp_transform

from app.ml import probability as prob
from app.ml.hazard import FEATURES_PATH, FEATURE_BANDS, NEAR_CHANNEL_M, SPARSE_COVER, _stack
from app.ml.model_b import GUZZETTI_A, GUZZETTI_B
from app.risk import LIVE_BBOX, level_index, risk_level
from app.trailscan import TrailScore, most_exposed, scan_trails
from app.weather import try_hourly_rain

TOP_TRAILS = 5
PREVIEW_CACHE_SECONDS = 300  # a preview is rescored at most this often; the rain cache is as long
MM_PER_INCH = 25.4

# Terrain thresholds for naming a point's primary factor. The slope and curvature cut-offs are
# the ones the hazard zone's driver hints use (app/ml/hazard.py _hints).
STEEP_SLOPE_DEG = 30
HOLLOW_CURVATURE = -0.2

FACTOR_WORDS = {
    "drainage": "Drainage channel",
    "hollow": "Concave hollow",
    "steep": "Steep slopes",
    "sparse": "Sparse vegetation",
    "wet": "Wet ground",
    "terrain": "Terrain susceptibility",
}


@dataclass(frozen=True)
class TrailRiskItem:
    trail_id: str
    name: str
    score: float
    mean_probability: float
    share_high: float
    level: str
    point: tuple[float, float] | None  # lon, lat of the worst sample
    slope_deg: float | None
    primary_factor: str
    length_mi: float | None


@dataclass(frozen=True)
class TrailRiskResult:
    method: str
    source: str  # "run" or "preview"
    computed_at: datetime
    score: float
    level: str
    map_mean: float | None
    map_share_high: float | None
    mean_slope_deg: float | None
    area_km2: float
    trails: list[TrailRiskItem]
    preventative: list[str]


def bbox_area_km2(bbox: tuple[float, float, float, float] = LIVE_BBOX) -> float:
    """Area of a [west, south, east, north] box on a sphere, in km2, to the nearest whole km2."""
    west, south, east, north = bbox
    km_per_deg = 111.2
    mid = math.radians((south + north) / 2)
    return round((east - west) * km_per_deg * math.cos(mid) * (north - south) * km_per_deg)


def _published() -> prob.ProbabilityMap | None:
    """The map the last run (or python -m app.assessment --save) wrote, or None."""
    path = prob.PROBABILITY_PATH
    if not path.is_file():
        return None
    with rasterio.open(path) as src:
        values = src.read(1).astype("float32")
        method = src.tags().get("METHOD") or prob.MODEL_B_METHOD
        return prob.ProbabilityMap(values, src.transform, src.crs.to_string(), method)


def _terrain_at(probability: prob.ProbabilityMap, point: tuple[float, float] | None,
                features_path: Path = FEATURES_PATH) -> tuple[float | None, str]:
    """Slope in degrees and the primary factor at one lon, lat. (None, terrain) without the stack."""
    if point is None or not features_path.exists():
        return None, FACTOR_WORDS["terrain"]
    data, box = _stack(features_path, features_path.stat().st_mtime_ns)
    if data.shape[1:] != probability.values.shape:
        return None, FACTOR_WORDS["terrain"]
    xs, ys = warp_transform("EPSG:4326", probability.crs, [point[0]], [point[1]])
    col, row = ~probability.transform @ (xs[0], ys[0])
    row, col = int(math.floor(row)), int(math.floor(col))
    if not (0 <= row < data.shape[1] and 0 <= col < data.shape[2]):
        return None, FACTOR_WORDS["terrain"]
    cell = {name: float(data[i, row, col]) for i, name in enumerate(FEATURE_BANDS)}
    slope = None if math.isnan(cell["slope"]) else round(cell["slope"], 1)
    # First match wins: the water-driven factors first, because they turn a slide into a debris flow.
    if cell["dist_drainage"] <= NEAR_CHANNEL_M:
        factor = "drainage"
    elif cell["curvature"] <= HOLLOW_CURVATURE:
        factor = "hollow"
    elif slope is not None and slope >= STEEP_SLOPE_DEG:
        factor = "steep"
    elif not math.isnan(cell["landcover"]) and int(cell["landcover"]) in SPARSE_COVER:
        factor = "sparse"
    elif cell["twi"] >= box["twi_p75"]:
        factor = "wet"
    else:
        factor = "terrain"
    return slope, FACTOR_WORDS[factor]


def _mean_slope(probability: prob.ProbabilityMap, features_path: Path = FEATURES_PATH) -> float | None:
    if not features_path.exists():
        return None
    data, _ = _stack(features_path, features_path.stat().st_mtime_ns)
    slope = data[FEATURE_BANDS.index("slope")]
    return round(float(np.nanmean(slope)), 1) if np.isfinite(slope).any() else None


def _preventative(items: list[TrailRiskItem]) -> list[str]:
    """One measure per trail, by its primary factor. Only trails at high or above get one."""
    rain_24h_in = GUZZETTI_A * 24 ** GUZZETTI_B * 24 / MM_PER_INCH
    lines: list[str] = []
    for item in items:
        if level_index(item.level) < level_index("high"):
            continue
        factor = item.primary_factor
        if factor == FACTOR_WORDS["drainage"]:
            lines.append(f"Post a debris-flow advisory at the {item.name} trailhead.")
        elif factor == FACTOR_WORDS["hollow"] or factor == FACTOR_WORDS["wet"]:
            lines.append(f"Clear culverts and drains on the {item.name} before the next storm.")
        elif factor == FACTOR_WORDS["steep"]:
            lines.append(f"Walk the {item.name} after any 24-hour rain above {rain_24h_in:.1f} in "
                         "and look for fresh slumps.")
        elif factor == FACTOR_WORDS["sparse"]:
            lines.append(f"Check the {item.name} for loose rock and erosion before the next storm.")
        else:
            lines.append(f"Add the {item.name} to the next patrol after heavy rain.")
    if not lines:
        lines.append("No trail reaches high on the current map. Keep the routine patrol schedule.")
    return lines


def _build(scores: list[TrailScore], probability: prob.ProbabilityMap, source: str) -> TrailRiskResult:
    items: list[TrailRiskItem] = []
    for score in scores[:TOP_TRAILS]:
        slope, factor = _terrain_at(probability, score.worst_point)
        items.append(TrailRiskItem(
            trail_id=score.trail_id, name=score.name, score=score.max_probability,
            mean_probability=score.mean_probability, share_high=score.share_high, level=score.level,
            point=score.worst_point, slope_deg=slope, primary_factor=factor, length_mi=score.length_mi,
        ))
    overall = round(sum(i.score for i in items) / len(items), 3) if items else 0.0
    summary = prob.summarize(probability.values)
    share_high = None
    if summary["cells"]:
        share_high = round(summary["share"]["high"] + summary["share"]["extreme"], 3)
    return TrailRiskResult(
        method=probability.method, source=source, computed_at=datetime.now(UTC),
        score=overall, level=risk_level(overall), map_mean=summary["mean"], map_share_high=share_high,
        mean_slope_deg=_mean_slope(probability), area_km2=bbox_area_km2(), trails=items,
        preventative=_preventative(items),
    )


def _latest_zone(conn: psycopg.Connection, slug: str) -> dict | None:
    """The newest hazard's polygon for the mountain, or None."""
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            """
            SELECT h.geom FROM hazards h JOIN mountains m ON m.id = h.mountain_id
            WHERE m.slug = %s ORDER BY h.created_at DESC LIMIT 1
            """,
            (slug,),
        ).fetchone()
    geom = row["geom"] if row else None
    return geom if isinstance(geom, dict) and geom.get("type") == "Polygon" else None


_lock = threading.Lock()
_cached: dict[str, tuple[object, float, TrailRiskResult]] = {}


def trail_risk(conn: psycopg.Connection, slug: str, peak: tuple[float, float]) -> TrailRiskResult:
    """The five most exposed trails on the current map. Cached until the map changes."""
    published = prob.PROBABILITY_PATH
    key = published.stat().st_mtime_ns if published.is_file() else None
    with _lock:
        hit = _cached.get(slug)
        if hit is not None and hit[0] == key and (key is not None or time.monotonic() - hit[1] < PREVIEW_CACHE_SECONDS):
            return hit[2]
    probability = _published()
    source = "run"
    if probability is None:
        rain, _ = try_hourly_rain(*peak)
        probability, source = prob.score(rain), "preview"
    # The same ranking the advisory's "avoid" list is drawn from (trailscan.most_exposed): a trail
    # crossing the latest hazard zone first, then the one most of whose walk is at high. The
    # lettered rows and the run's routes then name the same trails.
    zone = _latest_zone(conn, slug) if source == "run" else None
    scores = most_exposed(scan_trails(conn, slug, probability, zone_polygon=zone), TOP_TRAILS)
    result = _build(scores, probability, source)
    with _lock:
        _cached[slug] = (key, time.monotonic(), result)
    return result

