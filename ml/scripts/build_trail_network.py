#!/usr/bin/env python3
"""Build the walkable network the bypass routes on (implementation step 19).

Reads the step 14 cache of walkable OpenStreetMap segments and the step 10 DEM, and writes
data/seed/trail_network.geojson: every walkable edge within KEEP_RADIUS_M of the hero loop that
connects to it, split at junctions, with DEM elevations as a third coordinate.

The hero loop is not copied from OpenStreetMap. It is re-cut at each junction from the same
simplified line that data/seed/trail_segments.geojson came from, so every loop piece carries
from_mile and to_mile values that match the mile segments, and the other edges are snapped onto
it where they meet it.

The API (backend/app/bypass.py) routes on this file during each run. Run from the repo root:
  python ml/scripts/build_trail_network.py [--segments PATH] [--dem PATH] [--out PATH]
"""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

import import_trails as it
import networkx as nx
import numpy as np
import shapely
from shapely.ops import substring

NETWORK_PATH = it.REPO_ROOT / "data" / "seed" / "trail_network.geojson"

KEEP_RADIUS_M = 2500  # edges farther from the loop than this cannot make a sensible bypass
ON_LOOP_M = 3  # an OSM node this close to the loop is on it: a junction, or a piece of the loop itself
ELEVATION_STEP_M = 30  # vertex spacing for the elevation profile, about one DEM cell
COORD_DECIMALS = 6  # about 0.1 m


def lonlat_z(line_utm, dem: it.Dem) -> list[list[float]]:
    """A UTM line as [lon, lat, elevation m] vertices, at most ELEVATION_STEP_M apart."""
    dense = shapely.segmentize(line_utm, ELEVATION_STEP_M)
    xy = shapely.get_coordinates(dense)
    lon, lat = it.TO_LONLAT.transform(xy[:, 0], xy[:, 1])
    z = dem.sample(np.asarray(lon), np.asarray(lat))
    coords = [[round(float(x), COORD_DECIMALS), round(float(y), COORD_DECIMALS), round(float(h), 1)]
              for x, y, h in zip(lon, lat, z, strict=True)]
    # Rounding can repeat a vertex; drop repeats.
    return [c for i, c in enumerate(coords) if i == 0 or c[:2] != coords[i - 1][:2]]


def loop_point(loop, distance_m: float) -> tuple[float, float]:
    """The rounded [lon, lat] of the point `distance_m` along the UTM loop."""
    point = loop.interpolate(distance_m)
    lon, lat = it.TO_LONLAT.transform(point.x, point.y)
    return round(float(lon), COORD_DECIMALS), round(float(lat), COORD_DECIMALS)


def build(segments: list[dict], dem: it.Dem) -> tuple[dict, list[dict], list[dict]]:
    graph = it.walk_graph(segments)
    trails = it.trail_lines(segments)
    loop_raw = it.hero_loop(trails)
    # The exact line import_trails.py cut the mile segments from.
    loop = shapely.simplify(loop_raw, it.SIMPLIFY_M)
    length_m = loop.length

    # Drop OpenStreetMap's copy of the loop; the loop pieces below replace it.
    on_loop = []
    for u, v, data in graph.edges(data=True):
        middle = it.to_utm(shapely.LineString(data["coords"])).interpolate(0.5, normalized=True)
        if data["label"] in it.HERO_PARTS and loop_raw.distance(middle) <= ON_LOOP_M:
            on_loop.append((u, v))
    graph.remove_edges_from(on_loop)
    graph.remove_nodes_from([n for n in list(graph.nodes) if graph.degree(n) == 0])

    # Keep edges near the loop, then only the pieces of network that touch it.
    near = nx.Graph()
    for u, v, data in graph.edges(data=True):
        if loop_raw.distance(it.to_utm(shapely.LineString(data["coords"]))) <= KEEP_RADIUS_M:
            near.add_edge(u, v, **data)
    junctions = {n: loop.project(shapely.Point(it.TO_UTM.transform(*n))) for n in near.nodes
                 if loop_raw.distance(shapely.Point(it.TO_UTM.transform(*n))) <= ON_LOOP_M}
    keep = set()
    for component in nx.connected_components(near):
        if component & junctions.keys():
            keep |= component
    near = near.subgraph(keep).copy()

    # Snap each junction onto the loop, at the point the mile markers use.
    snapped = {n: loop_point(loop, d) for n, d in junctions.items()}

    features = []
    for u, v, data in near.edges(data=True):
        coords = [tuple(c) for c in data["coords"]]
        if tuple(coords[0]) != u:
            coords = coords[::-1]
        if u in snapped:
            coords[0] = snapped[u]
        if v in snapped:
            coords[-1] = snapped[v]
        line_utm = it.to_utm(shapely.LineString(coords))
        name = data["label"] if not data["label"].startswith("unnamed ") else None
        path_class = data["label"].removeprefix("unnamed ") if name is None else None
        features.append({
            "type": "Feature",
            "properties": {"trail": name, "hero": False, "class": path_class, "length_m": round(line_utm.length, 1)},
            "geometry": {"type": "LineString", "coordinates": lonlat_z(line_utm, dem)},
        })

    # The loop, cut at every junction. The trailhead (mile 0) is a node at both ends.
    cuts = sorted({0.0, length_m, *junctions.values()})
    cuts = [d for i, d in enumerate(cuts) if i == 0 or d - cuts[i - 1] > 0.5]
    if length_m - cuts[-1] > 0.5:
        cuts.append(length_m)
    for a, b in itertools.pairwise(cuts):
        piece = substring(loop, a, b)
        coords = lonlat_z(piece, dem)
        coords[0][:2] = loop_point(loop, a)
        coords[-1][:2] = loop_point(loop, b if b < length_m else 0.0)
        features.append({
            "type": "Feature",
            "properties": {
                "trail": it.HERO_TRAIL,
                "hero": True,
                "from_mile": round(a / it.METERS_PER_MILE, 3),
                "to_mile": round(b / it.METERS_PER_MILE, 3),
                "length_m": round(piece.length, 1),
            },
            "geometry": {"type": "LineString", "coordinates": coords},
        })

    header = {
        "type": "FeatureCollection",
        "attribution": it.ATTRIBUTION,
        "license": "ODbL-1.0",
        "source": it.SEGMENTS_URL,
        "hero_trail": it.HERO_TRAIL,
        "hero_length_mi": round(length_m / it.METERS_PER_MILE, 3),
        "elevation": "meters above the EGM2008 geoid, sampled from the Copernicus DEM (step 10)",
    }
    junction_list = sorted(
        ({"mile": round(d / it.METERS_PER_MILE, 2),
          "trails": sorted({near[n][w]["label"] for w in near[n]})} for n, d in junctions.items() if n in near),
        key=lambda j: j["mile"],
    )
    return header, features, junction_list


def write(header: dict, features: list[dict], path: Path) -> None:
    """One feature per line, like the other seed files."""
    lines = [json.dumps(f, ensure_ascii=False, separators=(",", ":")) for f in features]
    text = json.dumps(header, ensure_ascii=False)[:-1] + ', "features": [\n' + ",\n".join(lines) + "\n]}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the walkable network the bypass routes on.")
    parser.add_argument("--segments", type=Path, default=it.SEGMENTS_PATH, help="step 14 walkable segment cache")
    parser.add_argument("--dem", type=Path, default=it.DEM_PATH, help="step 10 DEM")
    parser.add_argument("--out", type=Path, default=NETWORK_PATH, help="seed file to write")
    args = parser.parse_args()

    for path, fix in ((args.segments, "python ml/scripts/import_trails.py --force"),
                      (args.dem, "python ml/scripts/download_sources.py --only dem")):
        if not path.exists():
            raise SystemExit(f"{it.rel(path)} is missing. Run `{fix}` first.")

    header, features, junctions = build(it.read_segments(args.segments), it.Dem(args.dem))
    write(header, features, args.out)
    hero = [f for f in features if f["properties"]["hero"]]
    other = [f for f in features if not f["properties"]["hero"]]
    names = sorted({f["properties"]["trail"] for f in other if f["properties"]["trail"]})
    print(f"wrote {it.rel(args.out)}: {len(hero)} loop pieces over {header['hero_length_mi']} mi, "
          f"{len(other)} other edges ({sum(f['properties']['length_m'] for f in other) / 1000:.1f} km), "
          f"{args.out.stat().st_size / 1e3:.0f} kB")
    print(f"{len(junctions)} junctions on the {it.HERO_TRAIL}:")
    for junction in junctions:
        print(f"  mile {junction['mile']:.2f}  {', '.join(junction['trails'])}")
    print(f"named trails in the network: {', '.join(names)}")


if __name__ == "__main__":
    main()
