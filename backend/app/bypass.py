"""The bypass around the flagged miles (step 19), routed on data/seed/trail_network.geojson.

A bypass leaves the hero trail at one junction, stays off it, and rejoins it at a junction past
the flagged miles. Of the detours that exist, it takes the one that keeps the hike closest to
the plan: the least walking on the detour plus the least trail given up, where a meter of high
or extreme ground on the detour counts 1 + HIGH_PENALTY times. The Trail Analyst explains the
result. Nothing here invents geometry: every meter is an OpenStreetMap trail in the network file,
which ml/scripts/build_trail_network.py writes.

When no detour exists, as on the upper loop where no other trail runs beside it, or the only one
gives up more than MAX_SKIPPED_MI of unflagged trail, the answer is None and the alert tells
hikers to turn back instead.
"""

import itertools
import json
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import networkx as nx

from app.config import REPO_ROOT
from app.ml.hazard import FlaggedRun, sample_max
from app.ml.probability import ProbabilityMap
from app.risk import HIGH_THRESHOLD, RiskLevel, risk_level

NETWORK_PATH = REPO_ROOT / "data" / "seed" / "trail_network.geojson"

SEARCH_MI = 3.0  # junctions this far before and after the flagged miles can start or end a bypass
MAX_SKIPPED_MI = 2.0  # unflagged trail a bypass may give up; past that it is a different hike, not a bypass
HIGH_PENALTY = 3.0  # a meter at high or above on the detour weighs 1 + HIGH_PENALTY meters
METERS_PER_MILE = 1609.344
CONNECTOR = "connector path"  # what an unnamed OpenStreetMap path is called in the via list

Node = tuple[float, float]


@dataclass(frozen=True)
class Edge:
    """A walkable edge off the hero trail, with [lon, lat, elevation m] vertices from u to v."""

    u: Node
    v: Node
    coords: tuple[tuple[float, float, float], ...]
    trail: str | None
    length_m: float


@dataclass(frozen=True)
class LoopPiece:
    """The hero trail between two junctions, walked in its own direction (mile going up)."""

    from_mile: float
    to_mile: float
    coords: tuple[tuple[float, float, float], ...]
    length_m: float


@dataclass(frozen=True)
class Network:
    trail: str
    length_mi: float
    off_trail: nx.Graph  # edges off the hero trail; each carries its Edge as "edge"
    loop: tuple[LoopPiece, ...]
    junctions: dict[Node, tuple[float, ...]]  # where other trails meet it, as loop miles (the trailhead: 0 and the end)


def _node(coordinate) -> Node:
    return (coordinate[0], coordinate[1])


@lru_cache(maxsize=2)
def _load(path: Path, mtime_ns: int) -> Network:
    """Parse the network. The mtime is part of the cache key, so a rebuilt file is picked up."""
    data = json.loads(path.read_text(encoding="utf-8"))
    graph = nx.Graph()
    pieces = []
    for feature in data["features"]:
        props = feature["properties"]
        coords = tuple(tuple(c) for c in feature["geometry"]["coordinates"])
        if props["hero"]:
            pieces.append(LoopPiece(props["from_mile"], props["to_mile"], coords, props["length_m"]))
            continue
        edge = Edge(_node(coords[0]), _node(coords[-1]), coords, props["trail"], props["length_m"])
        known = graph.get_edge_data(edge.u, edge.v)
        if known is None or known["edge"].length_m > edge.length_m:
            graph.add_edge(edge.u, edge.v, edge=edge)
    pieces.sort(key=lambda piece: piece.from_mile)
    junctions: dict[Node, set[float]] = {}
    for piece in pieces:
        for node, mile in ((_node(piece.coords[0]), piece.from_mile), (_node(piece.coords[-1]), piece.to_mile)):
            if node in graph:
                junctions.setdefault(node, set()).add(mile)
    return Network(
        trail=data["hero_trail"],
        length_mi=data["hero_length_mi"],
        off_trail=graph,
        loop=tuple(pieces),
        junctions={node: tuple(sorted(miles)) for node, miles in junctions.items()},
    )


def junctions_near(network: Network, start_mile: float, end_mile: float, margin_mi: float) -> list[dict]:
    """Junctions on the hero trail within margin_mi of a mile range, with the trails that meet there."""
    near = []
    for node, miles in network.junctions.items():
        for mile in miles:
            if start_mile - margin_mi <= mile <= end_mile + margin_mi:
                trails = sorted({data["edge"].trail or CONNECTOR for data in network.off_trail[node].values()})
                near.append({"mile": round(mile, 2), "trails": trails})
    return sorted(near, key=lambda junction: junction["mile"])


def load_network(path: Path = NETWORK_PATH) -> Network | None:
    """The trail network, or None until ml/scripts/build_trail_network.py has written it."""
    if not path.exists():
        return None
    return _load(path, path.stat().st_mtime_ns)


@dataclass(frozen=True)
class Bypass:
    name: str  # the named trail that carries most of the detour
    via: tuple[str, ...]  # every trail along the detour, in walking order
    leaves_at_mile: float
    rejoins_at_mile: float
    length_km: float
    replaced_km: float  # the hero trail the detour replaces, flagged miles included
    added_km: float  # length_km - replaced_km: negative when the detour is shorter
    added_elevation_m: int  # climb on the detour minus climb on the miles it replaces, walking the trail's way
    max_probability: float
    level: RiskLevel
    geom: dict  # GeoJSON LineString, [lon, lat], in walking order
    pieces: tuple[dict, ...]  # the detour edge by edge: trail, probability, level, geom

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "via": list(self.via),
            "leaves_at_mile": self.leaves_at_mile,
            "rejoins_at_mile": self.rejoins_at_mile,
            "length_km": self.length_km,
            "replaced_km": self.replaced_km,
            "added_km": self.added_km,
            "added_elevation_m": self.added_elevation_m,
            "max_probability": self.max_probability,
            "level": self.level,
            "geom": self.geom,
            "pieces": list(self.pieces),
        }


def _climb(coords) -> float:
    """Meters gained walking the vertices in order."""
    return sum(max(0.0, b[2] - a[2]) for a, b in itertools.pairwise(coords))


def _oriented(edge: Edge, start: Node) -> tuple[tuple[float, float, float], ...]:
    return edge.coords if edge.u == start else edge.coords[::-1]


def find_bypass(flagged: FlaggedRun | None, probability: ProbabilityMap,
                network: Network | None = None) -> Bypass | None:
    """The detour around the flagged miles, scored on this run's map, or None if none exists."""
    network = network or load_network()
    if network is None or flagged is None:
        return None
    graph = network.off_trail
    risk = {frozenset((u, v)): sample_max(probability, list(data["edge"].coords))
            for u, v, data in graph.edges(data=True)}

    def cost(u: Node, v: Node, data: dict) -> float:
        high = risk[frozenset((u, v))] >= HIGH_THRESHOLD
        return data["edge"].length_m * (1 + HIGH_PENALTY * high)

    start, end = flagged.start_mile, flagged.end_mile
    entries = [(n, m) for n, miles in network.junctions.items() for m in miles if start - SEARCH_MI <= m <= start]
    exits = [(n, m) for n, miles in network.junctions.items() for m in miles if end <= m <= end + SEARCH_MI]
    best = None  # (score, entry mile, exit mile, node path)
    for entry, a in entries:
        weights, paths = nx.single_source_dijkstra(graph, entry, weight=cost)
        for exit_node, b in exits:
            if exit_node == entry or exit_node not in weights:
                continue
            if (b - a) - (end - start) > MAX_SKIPPED_MI:
                continue
            score = weights[exit_node] + (b - a) * METERS_PER_MILE
            if best is None or score < best[0]:
                best = (score, a, b, paths[exit_node])
    if best is None:
        return None
    _, leaves, rejoins, path = best

    coords: list[tuple[float, float, float]] = []
    meters_by_trail: Counter = Counter()
    pieces, via = [], []
    for u, v in itertools.pairwise(path):
        edge = graph[u][v]["edge"]
        walked = _oriented(edge, u)
        coords.extend(walked if not coords else walked[1:])
        name = edge.trail or CONNECTOR
        meters_by_trail[edge.trail] += edge.length_m
        if not via or via[-1] != name:
            via.append(name)
        edge_risk = risk[frozenset((u, v))]
        pieces.append({
            "trail": edge.trail,
            "probability": edge_risk,
            "level": risk_level(edge_risk),
            "geom": {"type": "LineString", "coordinates": [[c[0], c[1]] for c in walked]},
        })
    named = [(meters, trail) for trail, meters in meters_by_trail.items() if trail]
    name = max(named)[1] if named else "the connector paths"

    replaced = [p for p in network.loop if p.from_mile >= leaves - 1e-6 and p.to_mile <= rejoins + 1e-6]
    length_m = sum(graph[u][v]["edge"].length_m for u, v in itertools.pairwise(path))
    replaced_m = sum(p.length_m for p in replaced)
    replaced_climb = sum(_climb(p.coords) for p in replaced)
    peak = max(piece["probability"] for piece in pieces)
    return Bypass(
        name=name,
        via=tuple(via),
        leaves_at_mile=round(leaves, 2),
        rejoins_at_mile=round(rejoins, 2),
        length_km=round(length_m / 1000, 2),
        replaced_km=round(replaced_m / 1000, 2),
        added_km=round((length_m - replaced_m) / 1000, 2),
        added_elevation_m=round(_climb(coords) - replaced_climb),
        max_probability=peak,
        level=risk_level(peak),
        geom={"type": "LineString", "coordinates": [[c[0], c[1]] for c in coords]},
        pieces=tuple(pieces),
    )
