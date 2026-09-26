"""Past landslides for a mountain's historical pins (step 14).

data/seed/landslides.geojson holds catalog points inside the Rainier box, written by
ml/scripts/download_sources.py. The file is read once and again only when it changes.
Until it exists, every mountain has no historical events.
"""

import json
from functools import lru_cache
from pathlib import Path

from app.config import REPO_ROOT
from app.models import HistoricalEvent
from app.risk import LIVE_SLUG

LANDSLIDES_PATH = REPO_ROOT / "data" / "seed" / "landslides.geojson"
# The catalog file covers one box: the live mountain's.
CATALOG_MOUNTAIN = LIVE_SLUG


@lru_cache(maxsize=2)
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


def historical_events(slug: str, path: Path = LANDSLIDES_PATH) -> list[HistoricalEvent]:
    """Catalog landslides for a mountain, oldest first. Empty until the catalog is downloaded."""
    if slug != CATALOG_MOUNTAIN or not path.exists():
        return []
    return list(_read(path, path.stat().st_mtime_ns))
