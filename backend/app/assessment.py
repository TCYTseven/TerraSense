"""Step 18 end to end for one mountain: the probability map, the trail's risk, and the hazard zone.

A run (step 22) calls assess() with the rain it fetched, then publish() and save_hazard() once
its agents finish. Before any run, the CLI makes the same map as a preview. From backend/:

    python -m app.assessment            print the map, the trail's risk, and the zone
    python -m app.assessment --save     also render the probability tiles, store each segment's
                                        risk, and store the zone as a preview hazard (run_id null)
"""

import argparse
import itertools
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import psycopg
import shapely
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from rasterio.warp import transform as warp_transform

from app.bypass import Bypass, find_bypass, load_network
from app.db import connect
from app.ml import probability as prob
from app.ml.hazard import (
    FlaggedRun,
    HazardZone,
    SegmentLine,
    SegmentRisk,
    flagged_run,
    hazard_zone,
    segment_risks,
)
from app.ml.tiles import render_xyz, slug_tiles_dir
from app.packs import get as get_pack, network_path, probability_path, susceptibility_path
from app.risk import RISK_LEVELS
from app.trailscan import TrailScore, scan_trails
from app.weather import HourlyRain, summarize as summarize_rain, try_hourly_rain

PROBABILITY_LAYER = "probability"
LIVE_SLUG = "mount-rainier"

HAZARD_WORDS = {"debris_flow": "Debris flow", "landslide": "Landslide"}
DRIVER_WORDS = {
    "slope_angle": "steep slopes",
    "drainage_proximity": "ground close to a drainage channel",
    "sparse_vegetation": "thin plant cover",
    "soil_wetness": "ground where water collects",
    "concave_hollow": "concave hollows",
}


class NoHeroTrail(RuntimeError):
    """The mountain has no trail with mile segments to score."""


@dataclass(frozen=True)
class HeroTrail:
    mountain_id: str
    trail_id: str
    name: str
    segments: list[SegmentLine]


@dataclass(frozen=True)
class Assessment:
    slug: str
    trail: HeroTrail
    probability: prob.ProbabilityMap
    map_summary: dict
    segments: list[SegmentRisk]
    flagged: FlaggedRun | None
    zone: HazardZone | None
    bypass: Bypass | None
    # Every mapped trail scored on the same map, so the advisory can name routes off the hero
    # trail. Empty only when the mountain has no trail geometry.
    trail_scores: list[TrailScore]
    computed_at: datetime
    elapsed_s: float

    @property
    def method(self) -> str:
        return self.probability.method

    def flagged_lines(self) -> list[SegmentLine]:
        seqs = set(self.flagged.seqs) if self.flagged else set()
        return [s for s in self.trail.segments if s.seq in seqs]


def hero_trail(conn: psycopg.Connection, slug: str = LIVE_SLUG) -> HeroTrail:
    """The trail with mile segments: the one the model scores mile by mile."""
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            """
            SELECT m.id AS mountain_id, t.id AS trail_id, t.name AS trail_name,
                   s.id AS segment_id, s.seq, s.start_mile, s.end_mile, s.geom
            FROM mountains m
            JOIN trails t ON t.mountain_id = m.id
            JOIN trail_segments s ON s.trail_id = t.id
            WHERE m.slug = %s
            ORDER BY t.name, s.seq
            """,
            (slug,),
        ).fetchall()
    if not rows:
        raise NoHeroTrail(f"{slug!r} has no trail with mile segments. Run python -m app.seed.")
    first = rows[0]
    segments = [
        SegmentLine(str(r["segment_id"]), r["seq"], r["start_mile"], r["end_mile"], r["geom"]["coordinates"])
        for r in rows
        if r["trail_id"] == first["trail_id"]
    ]
    return HeroTrail(str(first["mountain_id"]), str(first["trail_id"]), first["trail_name"], segments)


def assess(conn: psycopg.Connection, slug: str = LIVE_SLUG, rain: HourlyRain | None = None) -> Assessment:
    """Score the map, the hero trail, and the worst cluster it crosses. Writes nothing."""
    started = time.perf_counter()
    trail = hero_trail(conn, slug)
    probability = prob.score(rain, susceptibility=susceptibility_path(slug))
    risks = segment_risks(probability, trail.segments)
    flagged = flagged_run(risks)
    zone = None
    if flagged is not None:
        zone = hazard_zone(probability, [s for s in trail.segments if s.seq in flagged.seqs])
    return Assessment(
        slug=slug,
        trail=trail,
        probability=probability,
        map_summary=prob.summarize(probability.values),
        segments=risks,
        flagged=flagged,
        zone=zone,
        bypass=find_bypass(flagged, probability, network=load_network(network_path(slug))),
        trail_scores=scan_trails(conn, slug, probability, trail.trail_id,
                                 zone.polygon if zone is not None else None),
        computed_at=datetime.now(UTC),
        elapsed_s=round(time.perf_counter() - started, 2),
    )


def publish(conn: psycopg.Connection, assessment: Assessment) -> dict:
    """Render the probability tiles and store each segment's risk. Returns the layer metadata."""
    pack = get_pack(assessment.slug)
    if pack is None:
        raise RuntimeError(f"{assessment.slug!r} has no pack facts in data/seed/packs/index.json; "
                           "run python ml/scripts/mountain_packs.py --write-index")
    metadata = render_xyz(
        prob.write(assessment.probability, probability_path(assessment.slug)),
        PROBABILITY_LAYER,
        bbox=pack.bbox,
        tiles_dir=slug_tiles_dir(assessment.slug),
    )
    with conn.cursor() as cur:
        cur.executemany(
            "UPDATE trail_segments SET risk_level = %s, probability = %s WHERE id = %s",
            [(r.level, r.probability, r.id) for r in assessment.segments],
        )
    return metadata


def mile_text(start: float, end: float) -> str:
    """'mile 4.6 to 4.9': the spelled-out range sentences use."""
    return f"mile {start:.1f} to {end:.1f}"


KM_PER_MILE = 1.609344
FEET_PER_METER = 3.28084


def signed_miles(km: float) -> str:
    """-1.53 km to '-1.0 mi'. US units, as the design addendum's Units table sets them."""
    miles = round(km / KM_PER_MILE, 1) + 0.0  # + 0.0 turns -0.0 into 0.0
    return f"{miles:+.1f} mi"


def signed_feet(meters: float) -> str:
    """-94 m to '-310 ft', to the nearest 10 ft."""
    feet = int(round(meters * FEET_PER_METER / 10) * 10)
    return f"{feet:+,} ft"


def describe(assessment: Assessment) -> dict:
    """Plain what, why, and how-to-avoid lines from the facts alone.

    A preview hazard uses them, and a run falls back to them if the Alert Writer's text fails
    its checks twice. Step 19 names the bypass in how_to_avoid.
    """
    flagged, zone = assessment.flagged, assessment.zone
    if flagged is None or zone is None:
        return {"what": None, "why": None, "how_to_avoid": None}
    hazard = HAZARD_WORDS[zone.type_hint]
    what = f"{hazard} zone crossing the {assessment.trail.name}, {mile_text(flagged.start_mile, flagged.end_mile)}."
    source = "susceptibility map" if assessment.probability.is_stand_in else "72-hour map"
    reasons = [DRIVER_WORDS[d] for d in zone.drivers_hint]
    why = f"The {source} peaks at {flagged.max_probability:.2f} on these miles"
    why += f", with {_join(reasons)}." if reasons else "."
    bypass = assessment.bypass
    if bypass is not None:
        how = (f"Leave the {assessment.trail.name} at mile {bypass.leaves_at_mile:.1f} and take the {bypass.name} "
               f"to mile {bypass.rejoins_at_mile:.1f} ({signed_miles(bypass.added_km)}, "
               f"{signed_feet(bypass.added_elevation_m)}).")
    else:
        how = (f"No trail runs around {mile_text(flagged.start_mile, flagged.end_mile)}. "
               f"Turn back before mile {flagged.start_mile:.1f}.")
    return {"what": what, "why": why, "how_to_avoid": how}


def _join(words: list[str]) -> str:
    if len(words) <= 2:
        return " and ".join(words)
    return ", ".join(words[:-1]) + f", and {words[-1]}"


def save_hazard(
    conn: psycopg.Connection,
    assessment: Assessment,
    *,
    run_id: str | None = None,
    hazard_type: str | None = None,
    severity: str | None = None,
    confidence: float | None = None,
    drivers: list[str] | None = None,
    what: str | None = None,
    why: str | None = None,
    how_to_avoid: str | None = None,
    needs_review: bool = False,
) -> str:
    """Store the zone as a hazard row. Without a run_id it is a preview. Returns the hazard id."""
    flagged, zone = assessment.flagged, assessment.zone
    if flagged is None or zone is None:
        raise ValueError("no hazard zone to save: no trail segment reaches high")
    text = describe(assessment)
    values = (
        assessment.trail.mountain_id,
        run_id,
        hazard_type or zone.type_hint,
        severity or flagged.level,
        flagged.max_probability,
        confidence,
        Jsonb(zone.polygon),
        Jsonb(drivers if drivers is not None else list(zone.drivers_hint)),
        what or text["what"],
        why or text["why"],
        how_to_avoid or text["how_to_avoid"],
        needs_review,
        assessment.trail.trail_id,
        flagged.start_mile,
        flagged.end_mile,
        Jsonb(assessment.bypass.to_json()) if assessment.bypass else None,
    )
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            """
            INSERT INTO hazards
              (mountain_id, run_id, type, severity, probability, confidence, geom, drivers,
               what, why, how_to_avoid, needs_review, trail_id, start_mile, end_mile, bypass)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            values,
        ).fetchone()
    return str(row["id"])


def overlap_check(assessment: Assessment) -> float:
    """Meters between the bypass line and the flagged segments: 0 would mean the detour touches them."""
    crs = assessment.probability.crs

    def utm(coords):
        xs, ys = warp_transform("EPSG:4326", crs, [c[0] for c in coords], [c[1] for c in coords])
        return shapely.LineString(list(zip(xs, ys, strict=True)))

    flagged = shapely.union_all([utm(s.coordinates) for s in assessment.flagged_lines()])
    return utm(assessment.bypass.geom["coordinates"]).distance(flagged)


def level_runs(segments: list[SegmentRisk]) -> list[dict]:
    """Consecutive segments at the same level, as mile ranges: the trail's risk in a few lines."""
    runs = []
    for level, group in itertools.groupby(segments, key=lambda s: s.level):
        group = list(group)
        runs.append({
            "start_mile": group[0].start_mile,
            "end_mile": group[-1].end_mile,
            "level": level,
            "max_probability": max(s.probability for s in group),
        })
    return runs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--slug", default=LIVE_SLUG)
    parser.add_argument("--save", action="store_true",
                        help="render the probability tiles, store segment risk, and save a preview hazard")
    args = parser.parse_args()

    pack = get_pack(args.slug)
    rain, rain_error = try_hourly_rain(pack.peak_lat, pack.peak_lon) if pack else try_hourly_rain()
    with connect() as conn:
        assessment = assess(conn, args.slug, rain)
        summary = assessment.map_summary
        print(f"method: {assessment.method}")
        if rain is not None:
            rain_summary = summarize_rain(rain)
            print(f"rain ({rain_summary.source}): past 72h {rain_summary.past_72h_mm:.1f} mm, "
                  f"next 72h {rain_summary.next_72h_mm:.1f} mm, "
                  f"past 7d {rain_summary.past_7d_mm:.1f} mm")
        else:
            print(f"rain: unavailable ({rain_error or 'no response'})")
        print(f"map: {summary['cells']} cells, mean {summary['mean']}, max {summary['max']}; "
              + ", ".join(f"{level} {summary['share'][level]:.0%}" for level in RISK_LEVELS))
        print(f"{assessment.trail.name}: " + "; ".join(
            f"mi {r['start_mile']:.1f}-{r['end_mile']:.1f} {r['level']}" for r in level_runs(assessment.segments)))
        flagged, zone = assessment.flagged, assessment.zone
        if flagged is None or zone is None:
            print("no segment reaches high: no hazard zone")
        else:
            print(f"flagged: {mile_text(flagged.start_mile, flagged.end_mile)}, peak {flagged.max_probability}, "
                  f"{flagged.level}")
            print(f"zone: {zone.type_hint}, {zone.area_km2} km2 ({zone.cells} cells), peak {zone.max_probability}, "
                  f"mean {zone.mean_probability}, centroid {zone.centroid}, drivers {list(zone.drivers_hint)}, "
                  f"{len(zone.polygon['coordinates'][0])} outline vertices")
        bypass = assessment.bypass
        if flagged is not None and bypass is None:
            print("bypass: none. No trail in the network runs around the flagged miles")
        elif bypass is not None:
            print(f"bypass: {bypass.name}, leaves mile {bypass.leaves_at_mile} and rejoins mile {bypass.rejoins_at_mile}, "
                  f"{bypass.length_km} km instead of {bypass.replaced_km} km ({signed_miles(bypass.added_km)}, "
                  f"{signed_feet(bypass.added_elevation_m)}), via {', '.join(bypass.via)}, worst ground "
                  f"{bypass.max_probability} ({bypass.level}), {len(bypass.geom['coordinates'])} vertices")
            print(f"  closest approach to the flagged miles: {overlap_check(assessment):.0f} m")
        print(f"scored in {assessment.elapsed_s} s")

        if args.save:
            started = time.perf_counter()
            metadata = publish(conn, assessment)
            print(f"wrote {metadata['tile_count']} probability tiles (version {metadata['version']}) "
                  f"and {len(assessment.segments)} segment risks in {time.perf_counter() - started:.1f} s")
            if zone is not None:
                print(f"preview hazard {save_hazard(conn, assessment)}")


if __name__ == "__main__":
    main()
