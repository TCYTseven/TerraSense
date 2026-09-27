"""The mountain page's numbers, read from the saved one-week map (step 31).

The heat map tiles are rendered from each mountain's saved map (`app.packs.probability_path`),
which `Analyze now` and `python -m app.assessment --save` write. Before a pack has a weather
run, its rendered knowledge-driven susceptibility index is the displayed map and the fallback
scoring source. This module scores every trail against that same file, so the trail list, the
overall score, and the colors on the map always agree. Nothing here calls a model or weather feed.
"""

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import psycopg
import rasterio

from app.ml.hazard import point_terrain
from app.ml.model_b import RAINFALL_THRESHOLD_72H_MM
from app.ml.probability import ProbabilityMap, is_capped
from app.ml.probability import summarize as summarize_map
from app.hills import hill_bbox, hill_probability_path, hill_stack_path, is_hill
from app.risk import HIGH_THRESHOLD, risk_level
from app.packs import features_path, probability_path, susceptibility_path
from app.packs import get as get_pack
from app.trailscan import most_exposed, scan_trails

TOP_TRAILS = 5


def saved_map(path: Path) -> tuple[ProbabilityMap, datetime] | None:
    """The map the tiles were rendered from and when it was written, or None before the first save."""
    if not path.is_file():
        return None
    with rasterio.open(path) as src:
        values = src.read(1).astype("float32")
        tags = src.tags()
        grid = ProbabilityMap(values, src.transform, src.crs.to_string(), tags.get("METHOD", "unknown"),
                              capped=is_capped(tags))
    return grid, datetime.fromtimestamp(path.stat().st_mtime, UTC)


def _mean_slope(path: Path) -> float | None:
    """Mean slope in degrees from a feature stack's slope band, or None when that band is missing."""
    if not path.is_file():
        return None
    with rasterio.open(path) as src:
        names = list(src.descriptions)
        if "slope" not in names:
            return None
        band = src.read(names.index("slope") + 1)
    valid = band[np.isfinite(band)]
    if valid.size == 0:
        return None
    return round(float(valid.mean()), 1)


def risk_summary(conn: psycopg.Connection, slug: str, path: Path | None = None) -> dict | None:
    """Overall score, mean slope, and the top trails on the saved map. None before the first save."""
    if path is None and is_hill(slug):
        path = hill_probability_path(slug)
    if path is not None:
        loaded = saved_map(path)
    else:
        loaded = saved_map(probability_path(slug)) or saved_map(susceptibility_path(slug))
    if loaded is None:
        return None
    grid, scored_at = loaded
    scores = scan_trails(conn, slug, grid)
    top = most_exposed(scores, limit=TOP_TRAILS)

    trails = []
    box_mean_slope = None
    for score in top:
        terrain = (
            point_terrain(grid, *score.worst_point, features_path(slug))
            if score.worst_point
            else None
        )
        if terrain is not None:
            box_mean_slope = terrain.box_mean_slope_deg
        trails.append({
            "trail_id": score.trail_id,
            "name": score.name,
            "max_probability": round(score.max_probability, 4),
            "mean_probability": round(score.mean_probability, 4),
            "share_high": round(score.share_high, 4),
            "level": score.level,
            "worst_point": list(score.worst_point) if score.worst_point else None,
            "slope_deg": None if terrain is None else terrain.slope_deg,
            "factor": None if terrain is None else terrain.factor,
        })

    area = summarize_map(grid.values)
    valid = grid.values[np.isfinite(grid.values)]
    if scores:
        worst = max(s.max_probability for s in scores)
    elif is_hill(slug) and valid.size:
        # No trails: the score is the worst cell on this hill's own map.
        worst = float(np.nanmax(valid))
    else:
        worst = 0.0
    if box_mean_slope is None and is_hill(slug):
        box_mean_slope = _mean_slope(hill_stack_path(slug))
    pack = get_pack(slug)
    box = list(pack.bbox) if pack else None
    if box is None:
        hill_box = hill_bbox(slug)
        box = list(hill_box) if hill_box else None
    return {
        "method": grid.method,
        "scored_at": scored_at,
        "overall": {
            "score": round(worst, 4),
            "level": risk_level(worst),
            "trails_scored": len(scores),
            "share_area_high": round(float(np.mean(valid >= HIGH_THRESHOLD)), 4) if valid.size else 0.0,
            "area_mean": area["mean"],
        },
        "mean_slope_deg": box_mean_slope,
        "bbox": box,
        "threshold_72h_mm": round(RAINFALL_THRESHOLD_72H_MM, 1),
        "trails": trails,
    }
