"""Mountain catalog: committed data/seed/mountains.json only at runtime.

Regenerate that file offline (never on browser load), from backend/:

    python -m app.mountain_catalog --write-seed --source overpass
    python -m app.seed

GET /mountains reads Postgres. If the table is empty, the API loads the seed file once.
No Wikidata or Overpass calls in normal API operation.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Literal

import psycopg

from app.config import REPO_ROOT

log = logging.getLogger(__name__)

SEED_PATH = REPO_ROOT / "data" / "seed" / "mountains.json"
TARGET_COUNT = 1000
MIN_ELEVATION_M = 1800
USER_AGENT = "TerraSense/1.0 (hackathon; mountain catalog)"

# Smaller latitude slices so one Overpass call does not time out and we quota per band for a global globe.
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
    "https://overpass-api.de/api/interpreter",
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


def _overpass_band(south: float, north: float) -> list[dict]:
    # "out body" includes lat/lon; "out tags" does not, which broke seed generation.
    query = f'[out:json][timeout:90];node["natural"="peak"]["name"]["ele"]({south},-180,{north},180);out body;'
    body = urllib.parse.urlencode({"data": query}).encode()
    last_error: Exception | None = None
    for base in OVERPASS_URLS:
        request = urllib.request.Request(
            base,
            data=body,
            headers={"User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            payload = _http_json(request, timeout=180)
            break
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
    else:
        raise RuntimeError(f"Overpass did not answer: {last_error}") from last_error

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


def fetch_overpass_raw() -> list[dict]:
    rows: list[dict] = []
    for south, north in LATITUDE_BANDS:
        band_rows = _overpass_band(south, north)
        log.info("Overpass band %s..%s: %s peaks (>=%s m)", south, north, len(band_rows), MIN_ELEVATION_M)
        rows.extend(band_rows)
        time.sleep(1)
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


def pick_stratified(rows: list[dict], target: int = TARGET_COUNT) -> list[dict]:
    """Take the highest peaks in each latitude band so the globe is not all Antarctica/Andes."""
    deduped = dedupe_nearby(rows)
    quota = max(40, (target + len(LATITUDE_BANDS) - 1) // len(LATITUDE_BANDS))
    picked: list[dict] = []
    picked_keys: set[tuple[float, float]] = set()

    for south, north in LATITUDE_BANDS:
        band = sorted(
            (r for r in deduped if _in_band(r["lat"], south, north)),
            key=lambda r: -r["elevation_m"],
        )
        for row in band[:quota]:
            key = (round(row["lat"], 2), round(row["lon"], 2))
            if key in picked_keys:
                continue
            picked_keys.add(key)
            picked.append(row)
            if len(picked) >= target:
                return picked[:target]

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
    by_slug = {m["slug"]: m for m in raw_to_seed_rows(picked)}
    by_slug[RAINIER["slug"]] = RAINIER
    return sorted(by_slug.values(), key=lambda m: (-m["elevation_m"], m["name"]))


def read_seed_file() -> list[dict] | None:
    if not SEED_PATH.is_file():
        return None
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


def write_seed_file(*, source: Literal["wikidata", "overpass", "auto"] = "auto") -> int:
    if source == "overpass":
        rows, remote = fetch_overpass_raw(), "overpass"
    elif source == "wikidata":
        rows, remote = fetch_wikidata_raw(), "wikidata"
    else:
        rows, remote = fetch_remote_raw()
    mountains = build_seed_list(rows)
    SEED_PATH.write_text(json.dumps(mountains, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log.info("Wrote %s mountains to %s (remote source %s).", len(mountains), SEED_PATH, remote)
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
        choices=("auto", "wikidata", "overpass"),
        default="overpass",
        help="Remote source for --write-seed only (default overpass; avoids Wikidata rate limits)",
    )
    args = parser.parse_args()
    if args.write_seed:
        count = write_seed_file(source=args.source)
        print(f"Wrote {count} mountains to {SEED_PATH.relative_to(REPO_ROOT)}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
