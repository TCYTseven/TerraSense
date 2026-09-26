"""The hill seed: places scored by the existing landslide model, not catalog peaks.

data/seed/hills.json is the whole list. A mountain reseed does not read it, and
this module does not register a step 32 pack.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.config import REPO_ROOT

HILLS_PATH = REPO_ROOT / "data" / "seed" / "hills.json"
# Shared facts. EPSG:4326, [west, south, east, north].
TURTLE_SLUG = "turtle-mountain"
TURTLE_BBOX = (-114.48, 49.54, -114.34, 49.64)


@lru_cache(maxsize=1)
def _read(mtime_ns: int) -> tuple[dict, ...]:
    rows = json.loads(HILLS_PATH.read_text(encoding="utf-8"))
    return tuple(rows)


def hills() -> tuple[dict, ...]:
    """Every hill in the seed. Empty when the file is missing."""
    if not HILLS_PATH.is_file():
        return ()
    return _read(HILLS_PATH.stat().st_mtime_ns)


def is_hill(slug: str) -> bool:
    return any(row["slug"] == slug for row in hills())


def hill_bbox(slug: str) -> tuple[float, float, float, float] | None:
    """West, south, east, north. Only Turtle Mountain has a shared box."""
    if slug == TURTLE_SLUG and is_hill(slug):
        return TURTLE_BBOX
    return None


def hill_stack_path(slug: str) -> Path:
    """The hill's own feature stack. Missing until the terrain window is built."""
    return REPO_ROOT / "data" / "processed" / "hills" / slug / "features.tif"


def in_hill_bbox(slug: str, lat: float, lon: float) -> bool:
    box = hill_bbox(slug)
    if box is None:
        return False
    west, south, east, north = box
    return west <= lon <= east and south <= lat <= north
