"""Past landslides for a mountain's historical pins (steps 14 and 32).

Each mountain with a data pack has its own catalog file (Rainier's is
data/seed/landslides.geojson, a pack's is data/seed/packs/<slug>/landslides.geojson),
written by ml/scripts/download_sources.py. A file is read once and again only when it
changes. A mountain without a file, or with an empty one, has no historical events.
"""

import json
from functools import lru_cache
from pathlib import Path

from app import packs
from app.config import REPO_ROOT
from app.models import HistoricalEvent

LANDSLIDES_PATH = REPO_ROOT / "data" / "seed" / "landslides.geojson"


@lru_cache(maxsize=16)
def _read(path: Path, mtime_ns: int) -> tuple[HistoricalEvent, ...]:
    """Parse the catalog. The mtime is part of the cache key, so an edit is picked up."""
    features = json.loads(path.read_text(encoding="utf-8"))["features"]
    events = []
    for feature in features:
        props = feature["properties"]
        lon, lat = feature["geometry"]["coordinates"][:2]
        events.append(HistoricalEvent(
            id=str(props["id"]),
            date=props.get("date"),
            title=props.get("title"),
            category=props.get("category"),
            trigger=props.get("trigger"),
            location_accuracy=props.get("location_accuracy"),
            source_name=props.get("source_name"),
            source_link=props.get("source_link"),
            catalog=props.get("catalog") or "unknown",
            lon=lon,
            lat=lat,
        ))
    return tuple(events)


def historical_events(slug: str, path: Path | None = None) -> list[HistoricalEvent]:
    """Catalog landslides for a mountain, oldest first. Empty until the catalog is downloaded."""
    if path is None:
        if packs.get(slug) is None:
            return []  # no pack, no catalog box
        path = packs.landslides_path(slug)
    if not path.exists():
        return []
    return list(_read(path, path.stat().st_mtime_ns))
