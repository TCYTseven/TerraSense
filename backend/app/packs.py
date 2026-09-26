"""Pack facts and file paths for the demo peaks (implementation step 32).

data/seed/packs/index.json is the committed fact sheet, written by
`python ml/scripts/mountain_packs.py --write-index`: one row per pack with the peak,
the bbox, and the hero trail. This module reads it so the API never re-derives a
shared fact. Rainier keeps the legacy step 10-19 file paths; every other pack's
files live under packs/<slug>/ next to them.

A pack is *servable* once its susceptibility raster exists on this machine: that is
the one file scoring cannot run without. python -m app.seed marks servable packs
live, which is what opens the layer routes and Analyze now for them.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.config import REPO_ROOT

INDEX_PATH = REPO_ROOT / "data" / "seed" / "packs" / "index.json"
RAINIER_SLUG = "mount-rainier"

ARTIFACTS_DIR = REPO_ROOT / "ml" / "artifacts"
SEED_DIR = REPO_ROOT / "data" / "seed"


@dataclass(frozen=True)
class Pack:
    slug: str
    name: str
    peak_lat: float
    peak_lon: float
    peak_elevation_m: int
    bbox: tuple[float, float, float, float]  # (west, south, east, north), EPSG:4326
    hero_trail: str | None  # explicit hero (Rainier's Skyline Trail); packs pick theirs from data


@lru_cache(maxsize=2)
def _read(path: Path, mtime_ns: int) -> dict[str, Pack]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {
        slug: Pack(
            slug=slug,
            name=row["name"],
            peak_lat=row["peak_lat"],
            peak_lon=row["peak_lon"],
            peak_elevation_m=row["peak_elevation_m"],
            bbox=tuple(row["bbox"]),
            hero_trail=row.get("hero_trail"),
        )
        for slug, row in rows.items()
    }


def packs() -> dict[str, Pack]:
    """Every pack in the index, Rainier included. Empty when the index is not committed yet."""
    if not INDEX_PATH.exists():
        return {}
    return _read(INDEX_PATH, INDEX_PATH.stat().st_mtime_ns)


def get(slug: str) -> Pack | None:
    return packs().get(slug)


def _pack_file(slug: str, rainier_path: Path, pack_name: str, base: Path) -> Path:
    return rainier_path if slug == RAINIER_SLUG else base / "packs" / slug / pack_name


def susceptibility_path(slug: str) -> Path:
    return _pack_file(slug, ARTIFACTS_DIR / "susceptibility.tif", "susceptibility.tif", ARTIFACTS_DIR)


def probability_path(slug: str) -> Path:
    return _pack_file(slug, ARTIFACTS_DIR / "probability.tif", "probability.tif", ARTIFACTS_DIR)


def metrics_path(slug: str) -> Path:
    return _pack_file(slug, ARTIFACTS_DIR / "metrics.json", "metrics.json", ARTIFACTS_DIR)


def network_path(slug: str) -> Path:
    return _pack_file(slug, SEED_DIR / "trail_network.geojson", "trail_network.geojson", SEED_DIR)


def landslides_path(slug: str) -> Path:
    return _pack_file(slug, SEED_DIR / "landslides.geojson", "landslides.geojson", SEED_DIR)


def servable(slug: str) -> bool:
    """True when this pack's map can score: it is in the index and its raster is on disk."""
    return get(slug) is not None and susceptibility_path(slug).exists()


def servable_slugs() -> list[str]:
    return [slug for slug in packs() if servable(slug)]
