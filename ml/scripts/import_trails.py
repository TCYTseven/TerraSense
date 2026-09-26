#!/usr/bin/env python3
"""Import one mountain's trails from OpenStreetMap data (implementation steps 14 and 32).

The foot paths are OpenStreetMap ways, read from the Overture Maps transportation theme:
OSM-derived GeoParquet on AWS S3. Overpass and Geofabrik are not reachable from the build
container, and Overture needs no key. The script reads only the Parquet row groups whose
bbox statistics overlap the pack's bbox, about 300 MB of the 72 GB theme.

For Mount Rainier (the default) it writes, relative to the repo root:
  data/raw/rainier_trail_segments.geojson  every walkable segment in the bbox, clipped to it.
                                           Download cache, and the network step 19 routes on
  data/seed/trails.geojson                 one LineString per named trail, with length and gain
  data/seed/trail_segments.geojson         the hero trail cut into mile-marked segments

Any other pack in ml/scripts/mountain_packs.py writes the same three files under
data/raw/packs/<slug>/ and data/seed/packs/<slug>/.

Rainier's hero trail is the Skyline Trail loop above Paradise, an explicit pack fact. A pack
without one takes the longest named trail in its box, mile 0 at the lower trailhead. A box
whose OpenStreetMap ways carry no names gets an empty seed, never another mountain's trails —
unless OSM route relations name them (the Everest Base Camp Trek, Kilimanjaro's ascent
routes, all mapped as relations over nameless ways). Those come from Overpass, cached next
to the segment cache; an unreachable Overpass just keeps way names alone.

Run from the repo root:
  python ml/scripts/import_trails.py [--mountain SLUG] [--force] [--segments PATH] [--out PATH] [--dem PATH]
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import os
from collections import Counter, defaultdict
from pathlib import Path

import mountain_packs as mp
import networkx as nx
import numpy as np
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.fs as pafs
import rasterio
import requests
import shapely
from pyproj import Transformer
from scipy.ndimage import map_coordinates
from shapely.geometry import shape
from shapely.ops import substring

REPO_ROOT = Path(__file__).resolve().parents[2]

# Overture Maps release to read. The bucket keeps only the latest releases, so when this one
# disappears, set the newest name under s3://overturemaps-us-west-2/release/ and rerun with --force.
OVERTURE_RELEASE = "2026-09-23.0"
OVERTURE_BUCKET = "overturemaps-us-west-2"
OVERTURE_REGION = "us-west-2"
SEGMENTS_S3 = f"{OVERTURE_BUCKET}/release/{OVERTURE_RELEASE}/theme=transportation/type=segment/"
SEGMENTS_URL = f"https://{OVERTURE_BUCKET}.s3.amazonaws.com/release/{OVERTURE_RELEASE}/theme=transportation/type=segment/"

# Overture road classes a hiker can walk. They are the OSM highway=* values of the same names.
WALKABLE_CLASSES = ["footway", "path", "steps", "track", "bridleway", "pedestrian"]

# OSM route relations carry the walking-route names whose member ways have none of their
# own. Overpass serves relation membership (Overture segments do not); the public
# instances are often busy, so each URL gets a try and a miss only means way names alone.
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
ROUTE_KINDS = ("hiking", "foot", "trekking")  # the route=* values a hiker walks
FEW_NAMES = 3  # fewer distinct way names than this asks the route relations for more

# OSM-derived data is licensed ODbL 1.0 and must credit "© OpenStreetMap contributors".
# trails.geojson is a derived database, so it stays ODbL too.
ATTRIBUTION = f"© OpenStreetMap contributors (ODbL 1.0), via Overture Maps Foundation release {OVERTURE_RELEASE}"
SOURCE = "© OpenStreetMap contributors (ODbL), via Overture Maps"  # per-trail `source` property

SAMPLE_STEP_M = 30      # elevation profile spacing, about one DEM cell
SIMPLIFY_M = 5          # Douglas-Peucker tolerance for the seed lines
COORD_DECIMALS = 6      # about 0.1 m
BRIDGE_MAX_M = 150      # join two pieces of one trail name through the walkable network if they are this close
MIN_TRAIL_M = 200       # drop names whose line is shorter: campground labels such as "1", "G", "Group"
# OSM maps summit climbs (Disappointment Cleaver, Emmons Glacier, Camp Muir, Observation Rock)
# as footways named "... Route". They cross glaciers, not hiking trails, so the seed leaves them out.
CLIMBING_ROUTE_SUFFIX = " Route"

SEGMENT_MILES = 0.1  # one segment per tenth of a mile, so alerts can say "miles 1.2 to 2.1"
METERS_PER_MILE = 1609.344

# The pack this module works on. configure() swaps it; every function reads these at call
# time, so ml/scripts/build_trail_network.py shares one configured module.
PACK = mp.get(mp.RAINIER_SLUG)
PATHS = mp.paths(PACK.slug)
TO_UTM = Transformer.from_crs("EPSG:4326", PACK.utm_crs, always_xy=True)
TO_LONLAT = Transformer.from_crs(PACK.utm_crs, "EPSG:4326", always_xy=True)


def configure(slug: str) -> None:
    """Point the module at one pack: its bbox, paths, and UTM zone."""
    global PACK, PATHS, TO_UTM, TO_LONLAT
    PACK = mp.get(slug)
    PATHS = mp.paths(slug)
    TO_UTM = Transformer.from_crs("EPSG:4326", PACK.utm_crs, always_xy=True)
    TO_LONLAT = Transformer.from_crs(PACK.utm_crs, "EPSG:4326", always_xy=True)


def rel(path: Path) -> str:
    """Path relative to the repo root when it is inside the repo, for log lines."""
    return str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)


def to_utm(geom):
    return shapely.transform(geom, lambda xy: np.column_stack(TO_UTM.transform(xy[:, 0], xy[:, 1])))


def to_lonlat(geom):
    return shapely.transform(geom, lambda xy: np.column_stack(TO_LONLAT.transform(xy[:, 0], xy[:, 1])))


def round_coords(geom, decimals: int):
    return shapely.transform(geom, lambda xy: np.round(xy, decimals))


# --- Stage 1: walkable segments from Overture ------------------------------------------------


def overture_filesystem() -> pafs.S3FileSystem:
    """Anonymous S3 access. pyarrow reads SSL_CERT_FILE for TLS; HTTPS_PROXY must be passed in."""
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    return pafs.S3FileSystem(anonymous=True, region=OVERTURE_REGION, proxy_options=proxy or None)


def fetch_segments() -> list[dict]:
    """Walkable Overture segments that touch the pack's bbox, clipped to it, sorted by id."""
    west, south, east, north = PACK.bbox
    s3 = overture_filesystem()
    if s3.get_file_info(SEGMENTS_S3).type != pafs.FileType.Directory:
        releases = [i.base_name for i in s3.get_file_info(pafs.FileSelector(f"{OVERTURE_BUCKET}/release/"))]
        raise SystemExit(f"Overture release {OVERTURE_RELEASE} is gone. Available: {sorted(releases)}. "
                         "Set OVERTURE_RELEASE to the newest and rerun with --force.")
    dataset = ds.dataset(SEGMENTS_S3, filesystem=s3, format="parquet")
    # The bbox terms prune whole row groups by their min/max statistics before any rows are read.
    overlaps_bbox = (
        (pc.field("bbox", "xmin") <= east) & (pc.field("bbox", "xmax") >= west)
        & (pc.field("bbox", "ymin") <= north) & (pc.field("bbox", "ymax") >= south)
    )
    walkable = (pc.field("subtype") == "road") & pc.field("class").isin(WALKABLE_CLASSES)
    table = dataset.to_table(
        filter=overlaps_bbox & walkable,
        columns={
            "id": pc.field("id"),
            "class": pc.field("class"),
            "name": pc.field("names", "primary"),
            "sources": pc.field("sources"),
            "geometry": pc.field("geometry"),
        },
    )
    segments = []
    for row in table.to_pylist():
        line = shapely.from_wkb(row["geometry"])
        clipped = shapely.clip_by_rect(line, west, south, east, north)
        if clipped.is_empty:  # the bbox of the line overlaps, the line itself does not
            continue
        segments.append({
            "id": row["id"],
            "class": row["class"],
            "name": row["name"],
            # OSM way ids with version, e.g. "w407522640@2". One segment can come from several ways.
            "osm_ids": [s["record_id"] for s in row["sources"] or []
                        if s["dataset"] == "OpenStreetMap" and not s["property"]],
            "clipped": not clipped.equals(line),
            "geometry": clipped,
        })
    return sorted(segments, key=lambda s: s["id"])


def write_segments(segments: list[dict], path: Path) -> None:
    """Raw segments as GeoJSON at full OSM precision (7 decimals), so shared nodes stay equal."""
    features = [{
        "type": "Feature",
        "id": s["id"],
        "properties": {key: s[key] for key in ("id", "class", "name", "osm_ids", "clipped")},
        "geometry": json.loads(shapely.to_geojson(round_coords(s["geometry"], 7))),
    } for s in segments]
    collection = {
        "type": "FeatureCollection",
        "source": SEGMENTS_URL,
        "attribution": ATTRIBUTION,
        "features": features,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(collection, ensure_ascii=False) + "\n", encoding="utf-8")


def read_segments(path: Path) -> list[dict]:
    segments = [{**f["properties"], "geometry": shape(f["geometry"])}
                for f in json.loads(path.read_text(encoding="utf-8"))["features"]]
    apply_route_relations(segments, relations_cache_for(path))
    return segments


# --- Stage 1b: route-relation names for boxes whose ways are unnamed --------------------------


def relations_cache_for(segments_path: Path) -> Path:
    """The relation cache sits next to the segment cache, so the pair travels together."""
    return segments_path.with_name("route_relations.json")


def fetch_route_relations(cache_path: Path) -> None:
    """Cache the walking-route relations that touch the pack's bbox, with their parents.

    Treks are often mapped as unnamed stage relations under one named parent (the Everest
    Base Camp Trek), so the query pulls both. An unreachable Overpass writes nothing: the
    import keeps way names alone, exactly the pre-relation behavior, and tries again next
    run."""
    west, south, east, north = PACK.bbox
    query = (f'[out:json][timeout:120];relation["route"~"{"|".join(ROUTE_KINDS)}"]'
             f"({south},{west},{north},{east})->.r;(.r; relation(br.r););out body;")
    for url in OVERPASS_URLS:
        try:
            response = requests.post(url, data={"data": query},
                                     headers={"User-Agent": "TerraSense trail import"},
                                     timeout=(15, 150))
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            print(f"  {url.split('/')[2]}: {type(exc).__name__}")
            continue
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
        print(f"  cached {len(payload.get('elements', []))} route relations in {rel(cache_path)}")
        return
    print("  no Overpass instance answered; the seed keeps way names alone")


def resolve_relation_names(elements: list[dict]) -> list[dict]:
    """[{'name', 'ways'}] for every route relation the cache can name, longest first.

    A nameless stage relation takes the name of its most specific named parent (the one
    with the fewest members), so a shared stage goes to the Everest Base Camp Trek, not
    the Great Himalayan Trail."""
    by_id = {e["id"]: e for e in elements}
    parents = defaultdict(list)
    for e in elements:
        for member in e.get("members", []):
            if member.get("type") == "relation" and member["ref"] in by_id:
                parents[member["ref"]].append(e)
    resolved = []
    for e in elements:
        name = (e.get("tags") or {}).get("name")
        if not name:
            named = [p for p in parents.get(e["id"], []) if (p.get("tags") or {}).get("name")]
            if not named:
                continue
            name = min(named, key=lambda p: (len(p.get("members", [])), p["tags"]["name"]))["tags"]["name"]
        ways = [m["ref"] for m in e.get("members", []) if m.get("type") == "way"]
        if ways:
            resolved.append({"name": name, "ways": ways})
    return sorted(resolved, key=lambda r: (-len(r["ways"]), r["name"]))


def apply_route_relations(segments: list[dict], cache_path: Path) -> None:
    """Give unnamed segments the name of the cached walking route their OSM way is part of.

    Way-level names always win. A way on several routes takes the one with the most member
    ways, so a short variant never claims the main line. Relation-named trails skip the
    climbing-route and track-only filters below: route=hiking marks a walk by definition."""
    if not cache_path.exists():
        return
    relations = resolve_relation_names(json.loads(cache_path.read_text(encoding="utf-8")).get("elements", []))
    by_way = {}
    for relation in relations:
        for way in relation["ways"]:
            by_way.setdefault(way, relation["name"])
    named = 0
    for segment in segments:
        if segment["name"]:
            continue
        ways = sorted(int(osm_id[1:].split("@", 1)[0]) for osm_id in segment.get("osm_ids") or []
                      if osm_id.startswith("w"))
        for way in ways:
            if way in by_way:
                segment["name"] = by_way[way]
                segment["relation_named"] = True
                named += 1
                break
    if named:
        print(f"{len(relations)} walking-route relation(s) named {named} segments beyond their way names")


# --- Stage 2: one line per trail name ---------------------------------------------------------


def walk_graph(segments: list[dict]) -> nx.Graph:
    """Walkable network. Nodes are segment ends and shared OSM nodes (exact lon/lat), edges are meters.

    Overture keeps each OSM way whole, so trails often meet mid-segment: split at shared vertices.
    """
    lines = [(s, np.round(shapely.get_coordinates(part), 7))
             for s in segments for part in shapely.get_parts(s["geometry"])]
    users = defaultdict(set)
    for i, (_, coords) in enumerate(lines):
        for vertex in map(tuple, coords):
            users[vertex].add(i)
    graph = nx.Graph()
    for seg, coords in lines:
        cuts = [0] + [k for k in range(1, len(coords) - 1) if len(users[tuple(coords[k])]) > 1] + [len(coords) - 1]
        for a, b in itertools.pairwise(cuts):
            piece = coords[a:b + 1]
            meters = to_utm(shapely.LineString(piece)).length
            u, v = tuple(piece[0]), tuple(piece[-1])
            if u != v and (not graph.has_edge(u, v) or graph[u][v]["weight"] > meters):
                label = seg["name"] or f"unnamed {seg['class']}"
                graph.add_edge(u, v, weight=meters, coords=piece, label=label)
    return graph


def path_coords(graph: nx.Graph, nodes: list) -> np.ndarray:
    """Vertices along a node path, each edge oriented in travel order."""
    out = [np.array([nodes[0]])]
    for u, v in itertools.pairwise(nodes):
        coords = graph[u][v]["coords"]
        out.append((coords if tuple(coords[0]) == u else coords[::-1])[1:])
    return np.vstack(out)


def bridge_pieces(pieces: list, graph: nx.Graph) -> tuple[list, float, list[str]]:
    """Join pieces of one name through the walkable network where their ends are BRIDGE_MAX_M apart or less.

    OSM often leaves a short unnamed link inside a named trail (a plaza, a bridge, a junction).
    The link is real geometry, so the joined line never jumps. Returns the pieces, the meters added,
    and what the links run along. Pieces that meet mid-line (a T or a Y) cannot become one line and stay apart.
    """
    added, via = 0.0, set()
    while len(pieces) > 1:
        candidates = []  # (meters, -combined length, i, j, node path)
        for i, j in itertools.combinations(range(len(pieces)), 2):
            for a in (pieces[i].coords[0], pieces[i].coords[-1]):
                a = tuple(np.round(a, 7))
                if a not in graph:
                    continue
                reach, paths = nx.single_source_dijkstra(graph, a, cutoff=BRIDGE_MAX_M)
                for b in (pieces[j].coords[0], pieces[j].coords[-1]):
                    b = tuple(np.round(b, 7))
                    if b in reach:
                        size = to_utm(pieces[i]).length + to_utm(pieces[j]).length
                        candidates.append((reach[b], -size, i, j, paths[b]))
        join = None
        for candidate in sorted(candidates, key=lambda c: c[:4]):  # shortest link first, then the longest pair
            meters, _, i, j, nodes = candidate
            link = [shapely.LineString(path_coords(graph, nodes))] if len(nodes) > 1 else []
            joined = shapely.line_merge(shapely.MultiLineString([pieces[i], pieces[j], *link]))
            if joined.geom_type == "LineString":
                join = (meters, i, j, nodes, joined)
                break
        if join is None:
            break  # no candidate makes one line
        meters, i, j, nodes, joined = join
        pieces = [p for k, p in enumerate(pieces) if k not in (i, j)] + [joined]
        added += meters
        via |= {graph[u][v]["label"] for u, v in itertools.pairwise(nodes)}
    return pieces, added, sorted(via)


def trail_lines(segments: list[dict]) -> list[dict]:
    """Merge segments by OSM name. One record per name: every piece, and the one line the seed keeps."""
    by_name = defaultdict(list)
    for s in segments:
        if s["name"]:
            by_name[s["name"]].append(s)
    graph = walk_graph(segments)
    trails = []
    for name, segs in sorted(by_name.items()):
        merged = shapely.line_merge(shapely.MultiLineString(
            [part for s in segs for part in shapely.get_parts(s["geometry"])]))
        pieces = list(shapely.get_parts(merged))
        bridged, bridge_m, bridge_via = bridge_pieces(pieces, graph)
        # Keep the longest piece; its length decides which piece is "the" trail when OSM splits a name.
        lengths = [to_utm(p).length for p in bridged]
        keep = bridged[int(np.argmax(lengths))]
        trails.append({
            "name": name,
            "relation_named": any(s.get("relation_named") for s in segs),
            "classes": sorted({s["class"] for s in segs}),
            "segments": len(segs),
            "pieces": pieces,             # straight line_merge result
            "bridged": bridged,           # after joining short gaps through the network
            "bridge_m": bridge_m,
            "bridge_via": bridge_via,
            "line": keep,                 # lon/lat LineString the seed writes
            "total_m": sum(to_utm(p).length for p in pieces),
        })
    return trails


# --- Stage 3: measure and write the seed ------------------------------------------------------


class Dem:
    """Bilinear samples of the step 10 DEM (EPSG:4326, meters above the EGM2008 geoid)."""

    def __init__(self, path: Path):
        with rasterio.open(path) as src:
            self.z = src.read(1).astype("float64")
            self.inverse = ~src.transform

    def sample(self, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
        col, row = self.inverse * (np.asarray(lon), np.asarray(lat))
        # map_coordinates indexes pixel centers; the affine puts them at +0.5.
        return map_coordinates(self.z, [row - 0.5, col - 0.5], order=1, mode="nearest")

    def profile(self, line_utm) -> np.ndarray:
        """Elevations every SAMPLE_STEP_M along a UTM line, ends included."""
        n = max(2, math.ceil(line_utm.length / SAMPLE_STEP_M) + 1)
        xy = shapely.get_coordinates(shapely.line_interpolate_point(line_utm, np.linspace(0, line_utm.length, n)))
        lon, lat = TO_LONLAT.transform(xy[:, 0], xy[:, 1])
        return self.sample(lon, lat)


def uphill(line, dem: Dem):
    """Orient a lon/lat line to start at its lower end. Returns the line and its UTM profile."""
    profile = dem.profile(to_utm(line))
    if profile[0] > profile[-1]:
        return shapely.reverse(line), profile[::-1]
    return line, profile


def climb_m(profile: np.ndarray) -> float:
    """Sum of the rises between consecutive samples."""
    steps = np.diff(profile)
    return float(steps[steps > 0].sum())


def seed_feature(trail: dict, dem: Dem) -> dict:
    line, profile = uphill(trail["line"], dem)
    line_utm = to_utm(line)
    simple = round_coords(to_lonlat(shapely.simplify(line_utm, SIMPLIFY_M)), COORD_DECIMALS)
    coords = shapely.get_coordinates(simple)
    coords = coords[np.r_[True, np.any(np.diff(coords, axis=0) != 0, axis=1)]]  # drop repeats after rounding
    props = {
        "mountain_slug": PACK.slug,
        "name": trail["name"],
        "length_km": round(line_utm.length / 1000, 2),
        "elevation_gain_m": round(climb_m(profile)),
        "source": SOURCE,
    }
    notes = []
    if trail["bridge_m"] > 0:
        notes.append(f"Joined across {trail['bridge_m']:.0f} m of {', '.join(trail['bridge_via'])}")
    if len(trail["bridged"]) > 1:
        kept_km, total_km = line_utm.length / 1000, trail["total_m"] / 1000
        notes.append(f"Longest of {len(trail['bridged'])} OpenStreetMap pieces with this name that do not "
                     f"join into one line ({kept_km:.1f} of {total_km:.1f} km in the bbox)")
    if notes:
        props["note"] = ". ".join(notes) + "."
    return {"type": "Feature", "properties": props,
            "geometry": {"type": "LineString", "coordinates": coords.tolist()}}


def keep_in_seed(trail: dict) -> str | None:
    """Why a named line stays out of the seed, or None to keep it.

    Relation-named trails skip the track-only and climbing-route rules: those rules read
    way-level naming habits, and a route=hiking relation marks a walk by definition."""
    if trail["classes"] == ["track"] and not trail.get("relation_named"):
        return "forest or service road (track only)"
    if trail["name"].endswith(CLIMBING_ROUTE_SUFFIX) and not trail.get("relation_named"):
        return "summit climbing route"
    if to_utm(trail["line"]).length < MIN_TRAIL_M:
        return f"shorter than {MIN_TRAIL_M} m"
    return None


# --- Stage 4: the hero trail and its mile segments --------------------------------------------


def hero_loop(trails: list[dict], hero: mp.Hero):
    """An explicit closed hero in UTM: one loop from its trailhead, walked clockwise.

    Rainier's is the Skyline loop, clockwise as the park describes it: up the west side past
    Glacier Vista to Panorama Point, then down past the Golden Gate saddle and Myrtle Falls.
    """
    by_name = {t["name"]: t for t in trails}
    missing = [name for name in hero.parts if name not in by_name]
    if missing:
        raise SystemExit(f"hero trail parts missing from OpenStreetMap: {missing}")
    loop = shapely.line_merge(shapely.MultiLineString([by_name[name]["line"] for name in hero.parts]))
    if loop.geom_type != "LineString" or not loop.is_closed:
        raise SystemExit(f"{' + '.join(hero.parts)} no longer join into one closed loop ({loop.geom_type})")

    ring = to_utm(loop)
    coords = shapely.get_coordinates(ring)[:-1]  # the closing vertex repeats the first
    start = np.array(TO_UTM.transform(*hero.start))
    k = int(np.argmin(np.hypot(*(coords - start).T)))
    coords = np.vstack([coords[k:], coords[:k], coords[k:k + 1]])
    if shapely.Polygon(coords).exterior.is_ccw:
        coords = coords[::-1]
    return shapely.LineString(coords)


def hero_line(trails: list[dict], dem: Dem) -> tuple[str, object, object, tuple[str, ...]] | None:
    """The hero's name, its raw and simplified UTM lines with mile 0 first, and its OSM names.

    An explicit pack hero (Rainier's Skyline loop) joins its parts. Any other pack takes the
    longest named trail the seed keeps, mile 0 at the lower trailhead. The mile segments and
    the bypass network both cut the simplified line, so their miles always agree; the raw
    line is for distance tests against OpenStreetMap's own vertices. None when the box has
    no eligible named trail.
    """
    if PACK.hero and PACK.hero.closed:
        raw = hero_loop(trails, PACK.hero)
        return PACK.hero.trail, raw, shapely.simplify(raw, SIMPLIFY_M), PACK.hero.parts
    if PACK.hero:
        # An open explicit hero: one named trail, walked uphill like a pack's default hero.
        by_name = {t["name"]: t for t in trails}
        if PACK.hero.trail not in by_name:
            raise SystemExit(f"explicit hero {PACK.hero.trail!r} is not a named trail in the box")
        line, _ = uphill(by_name[PACK.hero.trail]["line"], dem)
        raw = to_utm(line)
        return PACK.hero.trail, raw, shapely.simplify(raw, SIMPLIFY_M), (PACK.hero.trail,)
    candidates = [t for t in trails if keep_in_seed(t) is None]
    if not candidates:
        return None
    best = max(candidates, key=lambda t: to_utm(t["line"]).length)
    line, _ = uphill(best["line"], dem)
    raw = to_utm(line)
    return best["name"], raw, shapely.simplify(raw, SIMPLIFY_M), (best["name"],)


def mile_segments(line_utm) -> list[tuple[float, float, object]]:
    """(start_mile, end_mile, UTM line) every SEGMENT_MILES. A short remainder joins the last segment."""
    step = SEGMENT_MILES * METERS_PER_MILE
    cuts = list(np.arange(0, line_utm.length, step))
    if line_utm.length - cuts[-1] < step / 2 and len(cuts) > 1:
        cuts.pop()
    cuts.append(line_utm.length)
    return [(a / METERS_PER_MILE, b / METERS_PER_MILE, substring(line_utm, a, b))
            for a, b in itertools.pairwise(cuts)]


def lonlat_coords(line_utm) -> list[list[float]]:
    """A UTM line as rounded lon/lat vertices, with repeats from rounding removed."""
    coords = shapely.get_coordinates(round_coords(to_lonlat(line_utm), COORD_DECIMALS))
    return coords[np.r_[True, np.any(np.diff(coords, axis=0) != 0, axis=1)]].tolist()


def hero_features(trails: list[dict], dem: Dem) -> tuple[dict | None, list[dict]]:
    """The hero trail's seed feature and its segment features, cut from the same simplified line.

    (None, []) when the box has no eligible named trail: the seed then honestly has no hero.
    """
    selection = hero_line(trails, dem)
    if selection is None:
        return None, []
    name, _, line, parts = selection
    profile = dem.profile(line)
    if PACK.hero and PACK.hero.closed:
        note = (f"The NPS loop: OpenStreetMap's {' and '.join(parts)}, joined. Starts at the Paradise "
                "trailhead and runs clockwise. Mile markers in trail_segments.geojson.")
    elif PACK.hero:
        note = ("The hero trail, named by the pack. Mile 0 is the lower trailhead. "
                "Mile markers in trail_segments.geojson.")
    else:
        note = ("The hero trail: the longest named trail in the box. Mile 0 is the lower trailhead. "
                "Mile markers in trail_segments.geojson.")
    trail = {
        "type": "Feature",
        "properties": {
            "mountain_slug": PACK.slug,
            "name": name,
            "length_km": round(line.length / 1000, 2),
            "elevation_gain_m": round(climb_m(profile)),
            "source": SOURCE,
            "note": note,
        },
        "geometry": {"type": "LineString", "coordinates": lonlat_coords(line)},
    }
    segments = [{
        "type": "Feature",
        "properties": {"mountain_slug": PACK.slug, "trail": name, "seq": seq,
                       "start_mile": round(start, 2), "end_mile": round(end, 2)},
        "geometry": {"type": "LineString", "coordinates": lonlat_coords(piece)},
    } for seq, (start, end, piece) in enumerate(mile_segments(line))]
    return trail, segments


def write_seed(features: list[dict], path: Path) -> None:
    """One feature per line, so a changed trail is a one-line diff."""
    head = {"type": "FeatureCollection", "attribution": ATTRIBUTION, "license": "ODbL-1.0", "source": SEGMENTS_URL}
    lines = [json.dumps(f, ensure_ascii=False, separators=(",", ":")) for f in features]
    text = json.dumps(head, ensure_ascii=False)[:-1] + ', "features": [\n' + ",\n".join(lines) + "\n]}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Import one mountain's trails from OpenStreetMap via Overture Maps.")
    parser.add_argument("--mountain", default=mp.RAINIER_SLUG,
                        help=f"pack slug from mountain_packs.py (default: {mp.RAINIER_SLUG})")
    parser.add_argument("--force", action="store_true", help="read Overture again even if the segment cache exists")
    parser.add_argument("--segments", type=Path, default=None, help="walkable segment cache (GeoJSON)")
    parser.add_argument("--out", type=Path, default=None, help="seed file to write")
    parser.add_argument("--dem", type=Path, default=None, help="step 10 DEM for elevation gain")
    parser.add_argument("--hero-segments", type=Path, default=None,
                        help="seed file for the hero trail's mile segments")
    args = parser.parse_args()
    configure(args.mountain)
    segments_path = args.segments or PATHS.segments_cache
    out_path = args.out or PATHS.trails
    dem_path = args.dem or PATHS.dem
    hero_segments_path = args.hero_segments or PATHS.hero_segments

    if not dem_path.exists():
        raise SystemExit(f"{rel(dem_path)} is missing. Run `python ml/scripts/download_sources.py "
                         f"--mountain {PACK.slug} --only dem` first.")
    if segments_path.exists() and not args.force:
        print(f"{rel(segments_path)} exists, skipping the Overture read (use --force to refresh)")
    else:
        print(f"reading walkable segments inside {list(PACK.bbox)} from {SEGMENTS_URL}")
        write_segments(fetch_segments(), segments_path)
        print(f"wrote {rel(segments_path)} ({segments_path.stat().st_size / 1e3:.0f} kB)")
    segments = read_segments(segments_path)  # always the cached copy, so a fresh read and a rerun match
    classes = Counter(s["class"] for s in segments)
    print(f"{len(segments)} walkable segments: " + ", ".join(f"{c} {n}" for c, n in classes.most_common())
          + f"; {sum(1 for s in segments if s['name'])} named")

    relations_path = relations_cache_for(segments_path)
    if len({s["name"] for s in segments if s["name"]}) < FEW_NAMES and not relations_path.exists():
        print(f"fewer than {FEW_NAMES} way names in the box; asking Overpass for walking-route relations")
        fetch_route_relations(relations_path)
        segments = read_segments(segments_path)  # picks the relation names up like any rerun

    dem = Dem(dem_path)
    trails = trail_lines(segments)
    hero, hero_segments = hero_features(trails, dem)
    hero_names = set(PACK.hero.parts) if PACK.hero else ({hero["properties"]["name"]} if hero else set())
    features, skipped = ([hero] if hero else []), []
    for trail in trails:
        if trail["name"] in hero_names:
            continue
        reason = keep_in_seed(trail)
        if reason:
            skipped.append(f"{trail['name']} ({reason})")
            continue
        features.append(seed_feature(trail, dem))
    features.sort(key=lambda f: f["properties"]["name"])
    write_seed(features, out_path)
    write_seed(hero_segments, hero_segments_path)

    joined = [f["properties"]["name"] for f in features if "Joined" in f["properties"].get("note", "")]
    split = [f["properties"]["name"] for f in features if "Longest" in f["properties"].get("note", "")]
    print(f"wrote {rel(out_path)}: {len(features)} named trails, "
          f"{sum(f['properties']['length_km'] for f in features):.1f} km, "
          f"{sum(len(f['geometry']['coordinates']) for f in features)} vertices, "
          f"{out_path.stat().st_size / 1e3:.0f} kB")
    print(f"  joined through the network: {', '.join(joined) or 'none'}")
    print(f"  longest piece kept: {', '.join(split) or 'none'}")
    print(f"  left out ({len(skipped)}): {', '.join(skipped)}")
    if hero is None:
        print(f"no eligible named trail inside {list(PACK.bbox)}: the seed has no hero and no mile segments")
        return
    props = hero["properties"]
    print(f"hero: {props['name']}, {props['length_km']} km ({props['length_km'] * 1000 / METERS_PER_MILE:.2f} mi), "
          f"gain {props['elevation_gain_m']} m, {len(hero_segments)} segments of {SEGMENT_MILES} mi "
          f"in {rel(hero_segments_path)}")


if __name__ == "__main__":
    main()
