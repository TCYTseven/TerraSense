#!/usr/bin/env python3
"""The mountain pack registry (implementation step 32).

A pack is the Rainier-style data bundle for one more mountain: DEM and land cover
windows, the 30 m feature stack, the knowledge-driven susceptibility index, XYZ tiles,
and the OpenStreetMap trails with a hero trail cut into mile segments. Steps 10-14
and 17-19 stay Rainier's; a pack reruns the same scripts with this registry's facts.

Two rules keep the packs honest (context: the Rainier scripts' contracts):

- Only Rainier has a landslide inventory, so only Rainier gets the trained LightGBM.
  Every other pack uses the knowledge-driven index and must stay labeled as an index.
- Rainier keeps its original file paths, so steps 10-19 and their docs do not move.
  Every other pack lives under a packs/<slug>/ folder next to the Rainier file.

Print the registry from the repo root, or write the index the API reads:
  python ml/scripts/mountain_packs.py [--write-index]
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
SEED_DIR = REPO_ROOT / "data" / "seed"
ARTIFACTS_DIR = REPO_ROOT / "ml" / "artifacts"

# Shared facts (context/implementation-steps.md). EPSG:4326, [west, south, east, north].
RAINIER_SLUG = "mount-rainier"
RAINIER_BBOX = (-121.93, 46.76, -121.54, 46.96)

# Copernicus DEM GLO-30 and ESA WorldCover 2021 v200, the same sources as step 10.
DEM_TILE_URL = (
    "https://copernicus-dem-30m.s3.amazonaws.com/"
    "Copernicus_DSM_COG_10_{lat}_00_{lon}_00_DEM/Copernicus_DSM_COG_10_{lat}_00_{lon}_00_DEM.tif"
)
LANDCOVER_TILE_URL = (
    "https://esa-worldcover.s3.eu-central-1.amazonaws.com/"
    "v200/2021/map/ESA_WorldCover_10m_2021_v200_{lat}{lon}_Map.tif"
)

EARTH_KM_PER_DEG = 111.32  # one degree of latitude, and of longitude at the equator


@dataclass(frozen=True)
class Hero:
    """An explicit hero trail. Packs without one take the longest named trail in the box."""

    trail: str                  # the seed's trail name
    parts: tuple[str, ...]      # OpenStreetMap names joined into the hero line
    start: tuple[float, float]  # (lon, lat) of mile 0
    closed: bool = False        # True when the parts must join into one closed loop


@dataclass(frozen=True)
class Pack:
    """One mountain's shared facts. Peak values match the catalog seed by slug."""

    slug: str
    name: str
    peak_lat: float
    peak_lon: float
    peak_elevation_m: int
    bbox: tuple[float, float, float, float]  # (west, south, east, north), EPSG:4326
    hero: Hero | None = None

    @property
    def utm_crs(self) -> str:
        """The metric CRS for this pack's 30 m grid: the peak's UTM zone."""
        zone = min(60, max(1, int((self.peak_lon + 180) // 6) + 1))
        return f"EPSG:{(32600 if self.peak_lat >= 0 else 32700) + zone}"

    @property
    def dem_urls(self) -> list[str]:
        """The 1x1 degree GLO-30 COG tiles the bbox touches, west to east, south to north."""
        return [DEM_TILE_URL.format(lat=_lat_tag(lat, 2), lon=_lon_tag(lon, 3))
                for lat, lon in _tile_corners(self.bbox, 1)]

    @property
    def landcover_urls(self) -> list[str]:
        """The 3x3 degree WorldCover COG tiles the bbox touches."""
        return [LANDCOVER_TILE_URL.format(lat=_lat_tag(lat, 2), lon=_lon_tag(lon, 3))
                for lat, lon in _tile_corners(self.bbox, 3)]


def _lat_tag(sw_lat: int, digits: int) -> str:
    return f"{'N' if sw_lat >= 0 else 'S'}{abs(sw_lat):0{digits}d}"


def _lon_tag(sw_lon: int, digits: int) -> str:
    return f"{'E' if sw_lon >= 0 else 'W'}{abs(sw_lon):0{digits}d}"


def _tile_corners(bbox: tuple, step: int) -> list[tuple[int, int]]:
    """South-west corners of the step-degree tiles the bbox touches. An edge exactly on a
    tile boundary needs no tile beyond it, hence the half-open ceil."""
    west, south, east, north = bbox
    lats = range(math.floor(south / step), math.ceil(north / step))
    lons = range(math.floor(west / step), math.ceil(east / step))
    return [(lat * step, lon * step) for lat in lats for lon in lons]


def bbox_around(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    """A bbox of +-radius_km around a summit, rounded outward to 3 decimals (about 100 m).

    Rainier's shared box reaches 15-16 km from its summit; that radius catches the
    trailheads on most peaks. Where the named routes start lower (Aconcagua's Horcones
    valley, Kilimanjaro's gates, Everest's Khumbu trails) the pack widens it once.
    """
    dlat = radius_km / EARTH_KM_PER_DEG
    dlon = radius_km / (EARTH_KM_PER_DEG * math.cos(math.radians(lat)))
    return (
        math.floor((lon - dlon) * 1000) / 1000,
        math.floor((lat - dlat) * 1000) / 1000,
        math.ceil((lon + dlon) * 1000) / 1000,
        math.ceil((lat + dlat) * 1000) / 1000,
    )


# One or two peaks per continent, next to Rainier. Peak facts copy data/seed/mountains_test.json.
PACKS = {
    pack.slug: pack
    for pack in (
        Pack(
            slug=RAINIER_SLUG,
            name="Mount Rainier",
            peak_lat=46.8523, peak_lon=-121.7603, peak_elevation_m=4392,
            bbox=RAINIER_BBOX,
            hero=Hero(
                trail="Skyline Trail",
                parts=("Skyline Trail", "Upper Skyline Trail"),
                start=(-121.73652, 46.78650),  # the Paradise trailhead
                closed=True,
            ),
        ),
        # North America: another Cascade volcano, with the Timberline loop well mapped.
        Pack(slug="mount-hood", name="Mount Hood",
             peak_lat=45.374, peak_lon=-121.696, peak_elevation_m=3429,
             bbox=bbox_around(45.374, -121.696, 15)),
        # South America: the Normal Route walks in through the Horcones valley, 18 km south.
        Pack(slug="aconcagua", name="Aconcagua",
             peak_lat=-32.653, peak_lon=-70.011, peak_elevation_m=6961,
             bbox=bbox_around(-32.653, -70.011, 20)),
        # Europe: the Zermatt side is dense with named paths up to the Hörnli Hut.
        Pack(slug="matterhorn", name="Matterhorn",
             peak_lat=45.976, peak_lon=7.659, peak_elevation_m=4478,
             bbox=bbox_around(45.976, 7.659, 15)),
        # Africa: the park gates and the Machame and Marangu routes sit 15-18 km out.
        Pack(slug="kilimanjaro", name="Kilimanjaro",
             peak_lat=-3.067, peak_lon=37.356, peak_elevation_m=5895,
             bbox=bbox_around(-3.067, 37.356, 18)),
        # Asia: the four fifth-station trails ring the summit within 10 km.
        Pack(slug="mount-fuji", name="Mount Fuji",
             peak_lat=35.361, peak_lon=138.727, peak_elevation_m=3776,
             bbox=bbox_around(35.361, 138.727, 15)),
        # Asia: the Khumbu trails (Gorak Shep, Base Camp, Kala Patthar) lie 8-12 km southwest.
        Pack(slug="mount-everest", name="Mount Everest",
             peak_lat=27.988, peak_lon=86.925, peak_elevation_m=8849,
             bbox=bbox_around(27.988, 86.925, 18)),
        # Oceania: the Hooker Valley Track runs to 14 km south of the summit.
        Pack(slug="aoraki-mount-cook", name="Aoraki / Mount Cook",
             peak_lat=-43.595, peak_lon=170.142, peak_elevation_m=3724,
             bbox=bbox_around(-43.595, 170.142, 15)),
    )
}


def get(slug: str) -> Pack:
    if slug not in PACKS:
        raise SystemExit(f"unknown mountain {slug!r}; packs: {', '.join(sorted(PACKS))}")
    return PACKS[slug]


@dataclass(frozen=True)
class PackPaths:
    """Where one pack's files live. Rainier keeps the step 10-19 paths unchanged."""

    dem: Path              # step 10 DEM window (data/raw, gitignored)
    landcover: Path        # step 10 WorldCover window (data/raw, gitignored)
    landslides: Path       # step 10 catalog points (committed; may be absent or empty)
    segments_cache: Path   # step 14 walkable-segment cache (data/raw, gitignored)
    stack: Path            # step 11 feature stack (data/processed, gitignored)
    table: Path            # step 11 labeled table (Rainier only; packs never write one)
    artifacts: Path        # step 12 susceptibility raster and metrics
    trails: Path           # step 14 named-trail seed (committed)
    hero_segments: Path    # step 14 hero mile segments (committed)
    network: Path          # step 19 bypass network (committed)


def paths(slug: str) -> PackPaths:
    get(slug)  # unknown slugs fail here, before any script writes a stray folder
    if slug == RAINIER_SLUG:
        return PackPaths(
            dem=RAW_DIR / "rainier_dem_cop30.tif",
            landcover=RAW_DIR / "rainier_landcover_worldcover2021.tif",
            landslides=SEED_DIR / "landslides.geojson",
            segments_cache=RAW_DIR / "rainier_trail_segments.geojson",
            stack=PROCESSED_DIR / "features.tif",
            table=PROCESSED_DIR / "features.parquet",
            artifacts=ARTIFACTS_DIR,
            trails=SEED_DIR / "trails.geojson",
            hero_segments=SEED_DIR / "trail_segments.geojson",
            network=SEED_DIR / "trail_network.geojson",
        )
    return PackPaths(
        dem=RAW_DIR / "packs" / slug / "dem_cop30.tif",
        landcover=RAW_DIR / "packs" / slug / "landcover_worldcover2021.tif",
        landslides=SEED_DIR / "packs" / slug / "landslides.geojson",
        segments_cache=RAW_DIR / "packs" / slug / "trail_segments.geojson",
        stack=PROCESSED_DIR / "packs" / slug / "features.tif",
        table=PROCESSED_DIR / "packs" / slug / "features.parquet",
        artifacts=ARTIFACTS_DIR / "packs" / slug,
        trails=SEED_DIR / "packs" / slug / "trails.geojson",
        hero_segments=SEED_DIR / "packs" / slug / "trail_segments.geojson",
        network=SEED_DIR / "packs" / slug / "trail_network.geojson",
    )


INDEX_PATH = SEED_DIR / "packs" / "index.json"


def write_index() -> None:
    """data/seed/packs/index.json: the shared facts the API needs, one row per pack.

    backend/app/packs.py reads this instead of importing the registry, so the two
    processes copy one committed file rather than re-deriving anything.
    """
    rows = {
        slug: {
            "name": pack.name,
            "peak_lat": pack.peak_lat,
            "peak_lon": pack.peak_lon,
            "peak_elevation_m": pack.peak_elevation_m,
            "bbox": list(pack.bbox),
            "utm_crs": pack.utm_crs,
            "hero_trail": pack.hero.trail if pack.hero else None,
        }
        for slug, pack in sorted(PACKS.items())
    }
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {INDEX_PATH.relative_to(REPO_ROOT)}: {len(rows)} packs")


def main() -> None:
    parser = argparse.ArgumentParser(description="Print the pack registry, or write the API's index.")
    parser.add_argument("--write-index", action="store_true", help="write data/seed/packs/index.json")
    args = parser.parse_args()
    if args.write_index:
        write_index()
        return
    for pack in PACKS.values():
        west, south, east, north = pack.bbox
        width_km = (east - west) * EARTH_KM_PER_DEG * math.cos(math.radians(pack.peak_lat))
        height_km = (north - south) * EARTH_KM_PER_DEG
        print(f"{pack.slug}: {pack.name}, peak ({pack.peak_lat}, {pack.peak_lon}) {pack.peak_elevation_m} m")
        print(f"  bbox {list(pack.bbox)} (~{width_km:.0f} x {height_km:.0f} km), grid {pack.utm_crs}")
        print(f"  dem tiles: {', '.join(url.rsplit('/', 1)[-1] for url in pack.dem_urls)}")
        print(f"  landcover tiles: {', '.join(url.rsplit('/', 1)[-1] for url in pack.landcover_urls)}")
        print(f"  hero: {pack.hero.trail if pack.hero else 'longest named trail in the box'}")


if __name__ == "__main__":
    main()
