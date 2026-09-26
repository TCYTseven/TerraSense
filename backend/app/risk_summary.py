"""The mountain page's numbers, read from the saved 72-hour map (step 31).

The heat map tiles are rendered from each mountain's saved map (`app.packs.probability_path`),
which `Analyze now` and `python -m app.assessment --save` write. This module scores every trail against that same file,
so the trail list, the overall score, and the colors on the map always agree. Nothing here
calls a model or a weather feed.
"""

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import psycopg
import rasterio

from app.ml.hazard import point_terrain
from app.ml.model_b import RAINFALL_THRESHOLD_72H_MM
from app.ml.probability import ProbabilityMap
from app.ml.probability import summarize as summarize_map
from app.risk import HIGH_THRESHOLD, risk_level
from app.packs import RAINIER_SLUG, probability_path
from app.packs import get as get_pack
from app.trailscan import most_exposed, scan_trails

TOP_TRAILS = 5


def saved_map(path: Path) -> tuple[ProbabilityMap, datetime] | None:
    """The map the tiles were rendered from and when it was written, or None before the first save."""
    if not path.is_file():
        return None
    with rasterio.open(path) as src:
        values = src.read(1).astype("float32")
        method = src.tags().get("METHOD", "unknown")
        grid = ProbabilityMap(values, src.transform, src.crs.to_string(), method)
    return grid, datetime.fromtimestamp(path.stat().st_mtime, UTC)


def risk_summary(conn: psycopg.Connection, slug: str, path: Path | None = None) -> dict | None:
    """Overall score, mean slope, and the top trails on the saved map. None before the first save."""
    loaded = saved_map(path or probability_path(slug))
    if loaded is None:
        return None
    grid, scored_at = loaded
    scores = scan_trails(conn, slug, grid)
    top = most_exposed(scores, limit=TOP_TRAILS)

    trails = []
    box_mean_slope = None
    for score in top:
        # The terrain stack is Rainier's grid only.
        terrain = point_terrain(grid, *score.worst_point) if score.worst_point and slug == RAINIER_SLUG else None
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

    worst = max((s.max_probability for s in scores), default=0.0)
    area = summarize_map(grid.values)
    valid = grid.values[np.isfinite(grid.values)]
    pack = get_pack(slug)
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
        "bbox": list(pack.bbox) if pack else None,
        "threshold_72h_mm": round(RAINFALL_THRESHOLD_72H_MM, 1),
        "trails": trails,
    }
