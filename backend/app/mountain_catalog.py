"""Mountain catalog: committed data/seed/mountains.json only at runtime.

Regenerate that file offline (never on browser load), from backend/:

    python -m app.mountain_catalog --write-seed --source overpass
    python -m app.seed

GET /mountains reads Postgres. If the table is empty, the API loads the seed file once.
No Wikidata or Overpass calls in normal API operation.
"""

from __future__ import annotations

import argparse
import http.client
import itertools
import json
import logging
import os
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal

import psycopg

from app.config import REPO_ROOT

log = logging.getLogger(__name__)

SEED_PATH = REPO_ROOT / "data" / "seed" / "mountains.json"
# Spaced worldwide sample. SEED_MODE=mountainstest loads this; SEED_MODE=reseed loads mountains.json.
TEST_SEED_PATH = REPO_ROOT / "data" / "seed" / "mountains_test.json"
# Raw Overpass rows land here (gitignored) so selection can be re-tuned without re-fetching.
RAW_CACHE_PATH = REPO_ROOT / "data" / "raw" / "overpass_peaks_raw.json"
TARGET_COUNT = 1000
# No two picked peaks within 1 degree (~110 km at the equator) of each other, or the
# globe renders a ridge line as one stack of overlapping pins.
SPACING_DEG = 1.0
# 1800 m keeps the Alps, US Rockies, and the Japanese Alps in while leaving out foothills
# that would flood the dense tiles. Overpass filters server-side, so payloads stay small.
MIN_ELEVATION_M = 1800
# Refuse to overwrite the committed seed with the husk of a fetch where most tiles failed.
MIN_SEED_ROWS = 500
USER_AGENT = "TerraSense/1.0 (hackathon; mountain catalog)"

# Overpass queries run per lat-band x lon-slice tile. A whole-band (360 degrees of
# longitude) query times out on the dense northern bands, which is how the seed ended up
# with Antarctica and Patagonia but one peak in the whole northern mid-latitudes.
LATITUDE_BANDS: tuple[tuple[float, float], ...] = (
    (-90, -60),
    (-60, -45),
    (-45, -30),
    (-30, -15),
    (-15, 15),
    (15, 30),
    (30, 45),
    (45, 60),
    (60, 75),
    (75, 90),
)
LON_SLICE_DEG = 30
LON_SLICES: tuple[tuple[float, float], ...] = tuple(
    (west, west + LON_SLICE_DEG) for west in range(-180, 180, LON_SLICE_DEG)
)
OVERPASS_TILE_RETRIES = 3
OVERPASS_TILE_SLEEP_S = 1.0
# Overpass scans every natural=peak node a bbox touches (~500 nodes/s observed), so a
# dense tile (the Alps, the Himalaya) blows the server timeout no matter the mirror. A
# tile that times out splits in half along its longer axis and the halves retry, up to:
MAX_TILE_SPLITS = 5
# 45 s, not 90: a too-dense probe fails twice as fast, and every tile that needs more
# than 45 s has always been better served split anyway (its halves answer in ~15 s).
OVERPASS_TIMEOUT_S = 45
# Coarse tiles fetch concurrently; each request starts on a different mirror, so the
# average load per public mirror stays at about one in-flight query.
OVERPASS_WORKERS = 4

RAINIER: dict[str, Any] = {
    "name": "Mount Rainier",
    "slug": "mount-rainier",
    "lat": 46.8523,
    "lon": -121.7603,
    "elevation_m": 4392,
    "region": "Cascade Range, Washington, USA",
    "current_risk_level": "moderate",
    "is_live": True,
}

WIKIDATA_SPARQL = """
SELECT ?mountain ?mountainLabel ?lat ?lon ?ele ?countryLabel WHERE {
  ?mountain wdt:P31/wdt:P279* wd:Q8502 .
  ?mountain wdt:P2044 ?ele .
  FILTER(?ele >= 2000)
  ?mountain p:P625 ?locStatement .
  ?locStatement ps:P625 ?coord .
  BIND(geof:latitude(?coord) AS ?lat)
  BIND(geof:longitude(?coord) AS ?lon)
  ?article schema:about ?mountain ;
           schema:isPartOf <https://en.wikipedia.org/> .
  OPTIONAL {
    ?mountain wdt:P17 ?country .
    ?country rdfs:label ?countryLabel .
    FILTER(LANG(?countryLabel) = "en")
  }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". ?mountain rdfs:label ?mountainLabel }
}
ORDER BY DESC(?ele)
LIMIT 1200
"""

WIKIDATA_PREFIXES = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX ps: <http://www.wikidata.org/prop/statement/>
PREFIX wikibase: <http://wikiba.se/ontology#>
PREFIX bd: <http://www.bigdata.com/rdf#>
PREFIX schema: <http://schema.org/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX geo: <http://www.opengis.net/ont/geosparql#>
PREFIX geof: <http://www.opengis.net/ont/geosparql#>
"""

OVERPASS_URLS = (
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)

Source = Literal["seed", "wikidata", "overpass", "none"]

_sync_lock = threading.Lock()


def slugify(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    text = re.sub(r"-+", "-", text)
    return (text[:96] or "peak").strip("-")


def display_risk(elevation_m: int) -> str:
    if elevation_m >= 6500:
        return "high"
    if elevation_m >= 4000:
        return "moderate"
    return "low"


def _http_json(request: urllib.request.Request, timeout: int = 120) -> dict:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def fetch_wikidata_raw() -> list[dict]:
    url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode(
        {"query": WIKIDATA_PREFIXES + WIKIDATA_SPARQL, "format": "json"},
    )
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
    )
    for attempt in range(3):
        try:
            payload = _http_json(request)
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 2:
                time.sleep(65)
                continue
            raise
    rows: list[dict] = []
    for binding in payload["results"]["bindings"]:
        rows.append(
            {
                "name": binding["mountainLabel"]["value"],
                "lat": float(binding["lat"]["value"]),
                "lon": float(binding["lon"]["value"]),
                "elevation_m": int(float(binding["ele"]["value"])),
                "region": binding.get("countryLabel", {}).get("value") or "Unknown",
            },
        )
    return rows


def iter_tiles() -> list[tuple[float, float, float, float]]:
    """Every (south, west, north, east) tile: LATITUDE_BANDS x LON_SLICES."""
    return [(south, west, north, east) for south, north in LATITUDE_BANDS for west, east in LON_SLICES]


def _tile_query(south: float, west: float, north: float, east: float) -> str:
    # "out body" includes lat/lon; "out tags" does not, which broke seed generation.
    # The (if:) filter drops low peaks server-side so dense tiles answer within the timeout.
    return (
        f"[out:json][timeout:{OVERPASS_TIMEOUT_S}];"
        f'node["natural"="peak"]["name"]["ele"]'
        f'(if:number(t["ele"])>={MIN_ELEVATION_M})'
        f"({south},{west},{north},{east});"
        "out body qt;"
    )


class TileTimeout(RuntimeError):
    """Overpass killed the query: the tile touches too many peak nodes for the timeout."""


_mirror_rotation = itertools.count()


def _overpass_query(query: str) -> dict:
    """POST one query, rotating mirrors and retrying with backoff before giving up.

    A timeout remark raises TileTimeout at once instead of retrying: the cost is the
    tile's node count, so every mirror fails it the same way — split the tile instead.
    """
    body = urllib.parse.urlencode({"data": query}).encode()
    start = next(_mirror_rotation) % len(OVERPASS_URLS)
    mirrors = OVERPASS_URLS[start:] + OVERPASS_URLS[:start]
    last_error: Exception | None = None
    for attempt in range(OVERPASS_TILE_RETRIES):
        for base in mirrors:
            request = urllib.request.Request(
                base,
                data=body,
                headers={"User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            try:
                payload = _http_json(request, timeout=OVERPASS_TIMEOUT_S + 45)
            except (OSError, http.client.HTTPException, ValueError) as exc:
                # OSError covers URLError/timeouts/connection resets; HTTPException covers
                # a body cut off mid-read; ValueError a non-JSON error page. One flaky
                # response must cost one request, not the whole multi-minute run.
                last_error = exc
                continue
            remark = payload.get("remark") or ""
            if "timed out" in remark or "out of memory" in remark:
                # Overpass reports these as HTTP 200 with a remark and no elements. The
                # cost is intrinsic to the tile, so no mirror will do better: split it.
                raise TileTimeout(remark)
            if remark:
                # Any other remark is a mirror-local fault; try the next mirror.
                last_error = RuntimeError(f"Overpass remark: {remark}")
                continue
            return payload
        if attempt < OVERPASS_TILE_RETRIES - 1:
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Overpass did not answer: {last_error}") from last_error


def _parse_peaks(payload: dict) -> list[dict]:
    rows: list[dict] = []
    for element in payload.get("elements", []):
        if element.get("type") != "node":
            continue
        if "lat" not in element or "lon" not in element:
            continue
        tags = element.get("tags") or {}
        name = tags.get("name:en") or tags.get("name")
        ele_raw = tags.get("ele")
        if not name or ele_raw is None:
            continue
        try:
            elevation_m = int(float(ele_raw))
        except ValueError:
            continue
        if elevation_m < MIN_ELEVATION_M:
            continue
        rows.append(
            {
                "name": name,
                "lat": float(element["lat"]),
                "lon": float(element["lon"]),
                "elevation_m": elevation_m,
                "region": tags.get("is_in:country") or tags.get("addr:country") or "OpenStreetMap",
            },
        )
    return rows


def _split_tile(
    south: float, west: float, north: float, east: float
) -> tuple[tuple[float, float, float, float], tuple[float, float, float, float]]:
    """Halve a tile along its longer axis."""
    if (east - west) >= (north - south):
        mid = (west + east) / 2
        return (south, west, north, mid), (south, mid, north, east)
    mid = (south + north) / 2
    return (south, west, mid, east), (mid, west, north, east)


def _fetch_tile(
    south: float,
    west: float,
    north: float,
    east: float,
    failed: list[tuple[float, float, float, float]],
    depth: int = 0,
) -> list[dict]:
    try:
        rows = _parse_peaks(_overpass_query(_tile_query(south, west, north, east)))
    except TileTimeout as exc:
        if depth < MAX_TILE_SPLITS:
            log.info("tile lat %s..%s lon %s..%s too dense; splitting", south, north, west, east)
            rows = []
            for half in _split_tile(south, west, north, east):
                rows.extend(_fetch_tile(*half, failed=failed, depth=depth + 1))
                time.sleep(OVERPASS_TILE_SLEEP_S)
            return rows
        failed.append((south, west, north, east))
        log.warning("tile lat %s..%s lon %s..%s FAILED at max depth: %s", south, north, west, east, exc)
        return []
    except RuntimeError as exc:
        failed.append((south, west, north, east))
        log.warning("tile lat %s..%s lon %s..%s FAILED: %s", south, north, west, east, exc)
        return []
    log.info(
        "tile lat %s..%s lon %s..%s: %s peaks (>=%s m)",
        south, north, west, east, len(rows), MIN_ELEVATION_M,
    )
    return rows


def fetch_overpass_raw() -> list[dict]:
    tiles = iter_tiles()
    rows: list[dict] = []
    failed: list[tuple[float, float, float, float]] = []
    done = 0
    with ThreadPoolExecutor(max_workers=OVERPASS_WORKERS) as pool:
        for tile_rows in pool.map(lambda tile: _fetch_tile(*tile, failed=failed), tiles):
            done += 1
            log.info("progress: %s/%s coarse tiles done", done, len(tiles))
            rows.extend(tile_rows)
    if failed:
        log.warning("%s tiles failed for good: %s", len(failed), failed)
    return rows


def fetch_remote_raw() -> tuple[list[dict], Source]:
    try:
        return fetch_wikidata_raw(), "wikidata"
    except Exception as exc:
        log.warning("Wikidata catalog fetch failed (%s); trying Overpass.", exc)
    return fetch_overpass_raw(), "overpass"


def dedupe_nearby(rows: list[dict], decimals: int = 2) -> list[dict]:
    seen: set[tuple[float, float]] = set()
    out: list[dict] = []
    for row in sorted(rows, key=lambda r: -r["elevation_m"]):
        key = (round(row["lat"], decimals), round(row["lon"], decimals))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def space_out(rows: list[dict], spacing_deg: float = SPACING_DEG) -> list[dict]:
    """Keep only the highest peak in any spacing_deg neighborhood.

    Highest first, so the summit survives and its subsidiary ridge peaks drop out.
    Neighbors are checked through a grid of spacing_deg cells, so this stays O(n).
    """
    taken: dict[tuple[int, int], tuple[float, float]] = {}
    out: list[dict] = []
    for row in sorted(rows, key=lambda r: -r["elevation_m"]):
        cell = (int(row["lat"] // spacing_deg), int(row["lon"] // spacing_deg))
        crowded = False
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                near = taken.get((cell[0] + di, cell[1] + dj))
                if near and abs(near[0] - row["lat"]) < spacing_deg and abs(near[1] - row["lon"]) < spacing_deg:
                    crowded = True
                    break
            if crowded:
                break
        if crowded:
            continue
        taken[cell] = (row["lat"], row["lon"])
        out.append(row)
    return out


def raw_to_seed_rows(rows: list[dict]) -> list[dict]:
    slugs: dict[str, int] = {}
    mountains: list[dict] = []
    for row in rows:
        base = slugify(row["name"])
        count = slugs.get(base, 0)
        slugs[base] = count + 1
        slug = base if count == 0 else f"{base}-{count + 1}"
        mountains.append(
            {
                "name": row["name"],
                "slug": slug,
                "lat": round(row["lat"], 4),
                "lon": round(row["lon"], 4),
                "elevation_m": row["elevation_m"],
                "region": row["region"],
                "current_risk_level": display_risk(row["elevation_m"]),
                "is_live": False,
            },
        )
    return mountains


def _in_band(lat: float, south: float, north: float) -> bool:
    if north >= 90:
        return lat >= south
    return south <= lat < north


def _band_index(lat: float) -> int:
    for i, (south, north) in enumerate(LATITUDE_BANDS):
        if _in_band(lat, south, north):
            return i
    return len(LATITUDE_BANDS) - 1


def _slice_index(lon: float) -> int:
    return min(int((lon + 180.0) // LON_SLICE_DEG), len(LON_SLICES) - 1)


def _band_quotas(counts: list[int], target: int) -> list[int]:
    """Split target evenly across the occupied bands.

    Bands are visited smallest-count first, so a band with fewer peaks than its
    share keeps what it has and the leftover flows to the fuller bands. Antarctica
    never outvotes the Alps just by having more raw rows.
    """
    quotas = [0] * len(counts)
    remaining_target = target
    remaining_bands = sum(1 for c in counts if c > 0)
    for i in sorted(range(len(counts)), key=lambda i: counts[i]):
        if counts[i] == 0 or remaining_bands == 0:
            continue
        share = -(-remaining_target // remaining_bands)
        quotas[i] = min(counts[i], share)
        remaining_target -= quotas[i]
        remaining_bands -= 1
    return quotas


def _pick_band(band_rows: list[dict], quota: int) -> list[dict]:
    """Fill a band's quota round-robin across its 30-degree longitude slices.

    Each slice offers its highest peaks first, so within one latitude band the
    Rockies, the Alps, the Himalaya, and Japan all land pins instead of whichever
    single range happens to be tallest.
    """
    slices: dict[int, list[dict]] = {}
    for row in band_rows:
        slices.setdefault(_slice_index(row["lon"]), []).append(row)
    ordered = [sorted(slices[i], key=lambda r: -r["elevation_m"]) for i in sorted(slices)]
    picked: list[dict] = []
    depth = 0
    while len(picked) < quota:
        took = False
        for slice_rows in ordered:
            if depth < len(slice_rows):
                picked.append(slice_rows[depth])
                took = True
                if len(picked) >= quota:
                    break
        if not took:
            break
        depth += 1
    return picked


def pick_stratified(rows: list[dict], target: int = TARGET_COUNT) -> list[dict]:
    """An even share per occupied latitude band, spread across longitude slices inside it,
    so the globe shows the Americas, Europe, and Asia — not only the polar deserts.
    Candidates are spaced SPACING_DEG apart first so pins never stack."""
    deduped = space_out(dedupe_nearby(rows))
    bands: list[list[dict]] = [[] for _ in LATITUDE_BANDS]
    for row in deduped:
        bands[_band_index(row["lat"])].append(row)

    picked: list[dict] = []
    picked_keys: set[tuple[float, float]] = set()
    for band_rows, quota in zip(bands, _band_quotas([len(b) for b in bands], target)):
        for row in _pick_band(band_rows, quota):
            key = (round(row["lat"], 2), round(row["lon"], 2))
            if key in picked_keys:
                continue
            picked_keys.add(key)
            picked.append(row)

    for row in sorted(deduped, key=lambda r: -r["elevation_m"]):
        if len(picked) >= target:
            break
        key = (round(row["lat"], 2), round(row["lon"], 2))
        if key in picked_keys:
            continue
        picked_keys.add(key)
        picked.append(row)
    return picked[:target]


def build_seed_list(rows: list[dict]) -> list[dict]:
    picked = pick_stratified(rows)
    # Rainier is merged in after selection, so give its pin the same breathing room.
    picked = [
        r for r in picked
        if abs(r["lat"] - RAINIER["lat"]) >= SPACING_DEG or abs(r["lon"] - RAINIER["lon"]) >= SPACING_DEG
    ]
    by_slug = {m["slug"]: m for m in raw_to_seed_rows(picked)}
    by_slug[RAINIER["slug"]] = RAINIER
    return sorted(by_slug.values(), key=lambda m: (-m["elevation_m"], m["name"]))


def catalog_seed_path() -> Path:
    """Which committed JSON the API and `app.seed` load.

    `SEED_MODE=mountainstest` (default) loads `mountains_test.json`.
    `SEED_MODE=reseed` loads the full Overpass dump in `mountains.json`.
    """
    mode = os.environ.get("SEED_MODE", "mountainstest").strip().lower()
    if mode == "reseed":
        return SEED_PATH
    if mode not in ("", "mountainstest"):
        log.warning("Unknown SEED_MODE %r; using mountainstest.", mode)
    if TEST_SEED_PATH.is_file():
        return TEST_SEED_PATH
    return SEED_PATH


def read_seed_file() -> list[dict] | None:
    path = catalog_seed_path()
    if not path.is_file():
        return None
    log.info("Loading mountain catalog from %s", path.name)
    return json.loads(path.read_text(encoding="utf-8"))


def distribution_note(mountains: list[dict]) -> str:
    lat_counts = {
        "south of -30": sum(1 for m in mountains if m["lat"] < -30),
        "tropics": sum(1 for m in mountains if -30 <= m["lat"] < 30),
        "north of 30": sum(1 for m in mountains if m["lat"] >= 30),
    }
    lon_counts = {
        "Americas": sum(1 for m in mountains if -180 <= m["lon"] <= -30),
        "Europe/Africa": sum(1 for m in mountains if -30 < m["lon"] <= 60),
        "Asia/Pacific": sum(1 for m in mountains if 60 < m["lon"] <= 180),
    }
    lat = ", ".join(f"{label} {count}" for label, count in lat_counts.items())
    lon = ", ".join(f"{label} {count}" for label, count in lon_counts.items())
    return f"lat: {lat} | lon: {lon}"


def write_seed_file(*, source: Literal["wikidata", "overpass", "auto", "cache"] = "auto") -> int:
    if source == "cache":
        rows, remote = json.loads(RAW_CACHE_PATH.read_text(encoding="utf-8")), "cache"
    elif source == "overpass":
        rows, remote = fetch_overpass_raw(), "overpass"
    elif source == "wikidata":
        rows, remote = fetch_wikidata_raw(), "wikidata"
    else:
        rows, remote = fetch_remote_raw()
    if source != "cache":
        # Selection can then be re-tuned offline: --write-seed --source cache
        RAW_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        RAW_CACHE_PATH.write_text(json.dumps(rows), encoding="utf-8")
        log.info("Cached %s raw rows to %s.", len(rows), RAW_CACHE_PATH)
    mountains = build_seed_list(rows)
    if len(mountains) < MIN_SEED_ROWS:
        raise SystemExit(
            f"Only {len(mountains)} mountains came back (< {MIN_SEED_ROWS}); most tiles must have "
            f"failed — see the tile logs above. {SEED_PATH} was NOT overwritten."
        )
    SEED_PATH.write_text(json.dumps(mountains, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log.info("Wrote %s mountains to %s (remote source %s).", len(mountains), SEED_PATH, remote)
    log.info("Distribution: %s", distribution_note(mountains))
    return len(mountains)


def upsert_mountains(conn: psycopg.Connection, mountains: list[dict]) -> int:
    for mountain in mountains:
        conn.execute(
            """
            INSERT INTO mountains
              (name, slug, lat, lon, elevation_m, region, current_risk_level, is_live)
            VALUES
              (%(name)s, %(slug)s, %(lat)s, %(lon)s, %(elevation_m)s, %(region)s,
               %(current_risk_level)s, %(is_live)s)
            ON CONFLICT (slug) DO UPDATE SET
              name = EXCLUDED.name,
              lat = EXCLUDED.lat,
              lon = EXCLUDED.lon,
              elevation_m = EXCLUDED.elevation_m,
              region = EXCLUDED.region,
              is_live = EXCLUDED.is_live,
              current_risk_level = CASE
                WHEN mountains.last_analyzed_at IS NULL THEN EXCLUDED.current_risk_level
                ELSE mountains.current_risk_level
              END
            """,
            mountain,
        )
    return len(mountains)


def mountain_count(conn: psycopg.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM mountains").fetchone()
    return int(row["n"] if row else 0)


def load_from_seed(conn: psycopg.Connection) -> Source:
    data = read_seed_file()
    if not data:
        return "none"
    upsert_mountains(conn, data)
    return "seed"


def sync_catalog(conn: psycopg.Connection) -> tuple[int, Source]:
    """Upsert mountains from data/seed/mountains.json (never calls Wikidata/Overpass)."""
    with _sync_lock:
        if mountain_count(conn) > 0:
            return mountain_count(conn), "seed"
        source = load_from_seed(conn)
        return mountain_count(conn), source


def ensure_catalog(conn: psycopg.Connection) -> None:
    if mountain_count(conn) == 0:
        sync_catalog(conn)


def main() -> None:
    parser = argparse.ArgumentParser(description="Mountain catalog seed tools.")
    parser.add_argument("--write-seed", action="store_true", help="Offline fetch; writes data/seed/mountains.json")
    parser.add_argument(
        "--source",
        choices=("auto", "wikidata", "overpass", "cache"),
        default="overpass",
        help="Remote source for --write-seed only (default overpass; avoids Wikidata rate "
        "limits). 'cache' reselects from the raw rows the last fetch stored in data/raw/.",
    )
    args = parser.parse_args()
    if args.write_seed:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        count = write_seed_file(source=args.source)
        print(f"Wrote {count} mountains to {SEED_PATH.relative_to(REPO_ROOT)}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
