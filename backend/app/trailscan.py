"""Every mapped trail on the mountain, scored against the 72-hour probability map.

Step 18 scores the hero trail mile by mile, because that is the trail the ranger alert closes
and the bypass routes around. The advisory needs more: to name three routes to avoid and three
that are safe today, the agents need the same numbers for all 67 trails in the seed.

Nothing here reads a model or invents a route. Each trail's geometry comes from the `trails`
table, and its exposure is the probability map sampled along the tread (app/ml/hazard.py).
The Route Scout reads the result as facts, and the code that checks the Risk Synthesizer's
answer uses it to reject a route the map does not support.
"""

from dataclasses import dataclass

import psycopg
import shapely
from psycopg.rows import dict_row
from rasterio.warp import transform as warp_transform

from app.ml.hazard import LineExposure, line_exposure
from app.ml.probability import ProbabilityMap
from app.risk import HIGH_THRESHOLD, RiskLevel, level_index, risk_level

KM_PER_MILE = 1.609344
FEET_PER_METER = 3.28084

# A route shorter than this is a spur or a viewpoint path, not a day hike. It can still be named
# as a route to avoid, but recommending one as "somewhere safe to go instead" is not useful.
MIN_RECOMMENDABLE_KM = 0.8
# A safe recommendation must stay under this. It is below HIGH_THRESHOLD on purpose: a trail that
# touches the top of the moderate bin is not what a ranger sends people to on a bad day.
SAFE_CEILING = 0.35


@dataclass(frozen=True)
class TrailScore:
    """One trail's exposure on today's map."""

    trail_id: str
    name: str
    length_km: float | None
    elevation_gain_m: int | None
    max_probability: float
    mean_probability: float
    share_high: float  # share of the walk at high or above
    level: RiskLevel
    worst_point: tuple[float, float] | None  # lon, lat
    is_hero: bool
    km_to_zone: float | None  # centre-line distance to the hazard zone, None without a zone
    crosses_zone: bool

    @property
    def length_mi(self) -> float | None:
        return None if self.length_km is None else round(self.length_km / KM_PER_MILE, 1)

    @property
    def gain_ft(self) -> int | None:
        if self.elevation_gain_m is None:
            return None
        return int(round(self.elevation_gain_m * FEET_PER_METER / 10) * 10)

    @property
    def recommendable(self) -> bool:
        """Long enough to send a hiker to, and clear enough on today's map."""
        return (self.length_km or 0) >= MIN_RECOMMENDABLE_KM and self.max_probability < SAFE_CEILING

    def to_json(self) -> dict:
        """The shape a tool hands a model. US units alongside the raw numbers."""
        return {
            "trail": self.name,
            "length_mi": self.length_mi,
            "elevation_gain_ft": self.gain_ft,
            "max_probability": self.max_probability,
            "mean_probability": self.mean_probability,
            "share_at_high_or_above": self.share_high,
            "level": self.level,
            "is_hero_trail": self.is_hero,
            "km_to_hazard_zone": self.km_to_zone,
            "crosses_hazard_zone": self.crosses_zone,
            "safe_to_recommend": self.recommendable,
        }


def _geometry(probability: ProbabilityMap, polygon: dict | None):
    """A GeoJSON polygon in the probability grid's CRS, for distance in meters."""
    if polygon is None:
        return None
    ring = polygon["coordinates"][0]
    xs, ys = warp_transform("EPSG:4326", probability.crs, [c[0] for c in ring], [c[1] for c in ring])
    return shapely.Polygon(list(zip(xs, ys, strict=True)))


def _line(probability: ProbabilityMap, coordinates: list[list[float]]):
    xs, ys = warp_transform("EPSG:4326", probability.crs,
                            [c[0] for c in coordinates], [c[1] for c in coordinates])
    return shapely.LineString(list(zip(xs, ys, strict=True)))


def scan_trails(conn: psycopg.Connection, slug: str, probability: ProbabilityMap,
                hero_trail_id: str | None = None, zone_polygon: dict | None = None) -> list[TrailScore]:
    """Score every trail on the mountain, worst first. Skips a trail with fewer than two vertices."""
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            """
            SELECT t.id, t.name, t.geom, t.length_km, t.elevation_gain_m
            FROM trails t JOIN mountains m ON m.id = t.mountain_id
            WHERE m.slug = %s ORDER BY t.name
            """,
            (slug,),
        ).fetchall()

    zone = _geometry(probability, zone_polygon)
    scores: list[TrailScore] = []
    for row in rows:
        coordinates = (row["geom"] or {}).get("coordinates") or []
        if len(coordinates) < 2:
            continue
        exposure: LineExposure = line_exposure(probability, coordinates)
        km_to_zone, crosses = None, False
        if zone is not None:
            meters = _line(probability, coordinates).distance(zone)
            km_to_zone = round(meters / 1000, 2)
            crosses = meters == 0.0
        scores.append(TrailScore(
            trail_id=str(row["id"]),
            name=row["name"],
            length_km=row["length_km"],
            elevation_gain_m=row["elevation_gain_m"],
            max_probability=exposure.max_probability,
            mean_probability=exposure.mean_probability,
            share_high=exposure.share_high,
            level=risk_level(exposure.max_probability),
            worst_point=exposure.worst_point,
            is_hero=hero_trail_id is not None and str(row["id"]) == str(hero_trail_id),
            km_to_zone=km_to_zone,
            crosses_zone=crosses,
        ))
    return sorted(scores, key=_worst_first)


def _worst_first(score: TrailScore) -> tuple:
    """A trail that crosses the zone comes first, then the one most of whose length is exposed.

    Peak alone is a poor ranking here: on a saturated map a dozen trails touch 1.0 at a single
    cell. What separates them for a ranger is how much of the walk sits at high or above.
    """
    return (not score.crosses_zone, -score.share_high, -score.max_probability, score.name)


def _cleanest_first(score: TrailScore) -> tuple:
    return (score.max_probability, score.mean_probability, -(score.length_km or 0))


def most_exposed(scores: list[TrailScore], limit: int = 8) -> list[TrailScore]:
    """The trails carrying the most risk today: the only candidates for "avoid"."""
    return [s for s in sorted(scores, key=_worst_first) if s.max_probability > 0][:limit]


def safest(scores: list[TrailScore], limit: int = 8) -> list[TrailScore]:
    """The cleanest trails worth walking, cleanest first: the only candidates for "safe".

    The list degrades rather than empties. On a day when the map puts almost the whole mountain
    at high, "safest" means least bad, and the advisory says so: relative_only below is the flag
    the Risk Synthesizer's caution sentence has to honour.
    """
    ranked = sorted(scores, key=_cleanest_first)
    walkable = [s for s in ranked if (s.length_km or 0) >= MIN_RECOMMENDABLE_KM]
    picked = [s for s in walkable if s.recommendable]
    for pool in (walkable, ranked):  # widen only as far as needed to fill the list
        for score in pool:
            if len(picked) >= limit:
                break
            if score not in picked:
                picked.append(score)
    return sorted(picked[:limit], key=_cleanest_first)


def relative_only(scores: list[TrailScore], needed: int = 3, limit: int = 8) -> bool:
    """True when the shortlist cannot fill `needed` trails that clear the safe ceiling.

    On such a day "safe" means least bad, and every caution sentence has to say so.
    """
    return sum(1 for s in safest(scores, limit) if s.recommendable) < needed


def by_name(scores: list[TrailScore]) -> dict[str, TrailScore]:
    """Lower-cased name to score, for matching a name a model wrote back to the catalog."""
    return {s.name.lower(): s for s in scores}


def resolve(scores: list[TrailScore], name: str) -> TrailScore | None:
    """The catalog entry a model meant, tolerating case and a missing or extra "Trail"."""
    catalog = by_name(scores)
    key = " ".join(name.split()).lower().strip(" .")
    if key in catalog:
        return catalog[key]
    stripped = key.removeprefix("the ").removesuffix(" trail")
    for candidate, score in catalog.items():
        if candidate.removesuffix(" trail") == stripped:
            return score
    return None


def summarize(scores: list[TrailScore]) -> dict:
    """The network in a few numbers, for the shared briefing."""
    if not scores:
        return {"trails": 0}
    counts: dict[str, int] = {}
    for score in scores:
        counts[score.level] = counts.get(score.level, 0) + 1
    worst = max(scores, key=lambda s: s.max_probability)
    return {
        "trails": len(scores),
        "by_level": counts,
        "at_high_or_above": sum(1 for s in scores if level_index(s.level) >= level_index("high")),
        "worst_trail": {"trail": worst.name, "max_probability": worst.max_probability, "level": worst.level},
        "clear_enough_to_recommend": sum(1 for s in scores if s.recommendable),
        "cleanest_trail": {"trail": (best := min(scores, key=_cleanest_first)).name,
                           "max_probability": best.max_probability, "level": best.level},
        "high_threshold": HIGH_THRESHOLD,
        "safe_ceiling": SAFE_CEILING,
    }
