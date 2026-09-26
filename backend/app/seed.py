"""Load data/seed/ into Postgres. From backend/: python -m app.seed

Mountains upsert by slug. Trails upsert by (mountain, name), and a mountain's
trails that are no longer in the file are removed. Trail segments (the hero
trail's mile markers) upsert by (trail, seq) the same way. Re-running is safe.
"""

import json

import psycopg
from psycopg.types.json import Jsonb

from app.config import REPO_ROOT
from app.db import connect
from app.mountain_catalog import read_seed_file, upsert_mountains

SEED_DIR = REPO_ROOT / "data" / "seed"


def load_mountains(conn: psycopg.Connection) -> int:
    """Upsert every mountain in mountains.json. Returns how many the file holds."""
    mountains = read_seed_file()
    if not mountains:
        raise SystemExit(f"Missing or empty {SEED_DIR / 'mountains.json'}. Run: python -m app.mountain_catalog --write-seed")
    return upsert_mountains(conn, mountains)


def load_trails(conn: psycopg.Connection) -> int:
    """Upsert every trail in trails.geojson. Returns how many the file holds.

    The file is the whole truth for trails: a mountain keeps only the trails it lists.
    """
    collection = json.loads((SEED_DIR / "trails.geojson").read_text(encoding="utf-8"))
    names_by_mountain: dict[str, list[str]] = {
        slug: [] for (slug,) in conn.execute("SELECT slug FROM mountains").fetchall()
    }

    for feature in collection["features"]:
        props, geometry = feature["properties"], feature["geometry"]
        if geometry["type"] != "LineString" or len(geometry["coordinates"]) < 2:
            raise SystemExit(f"trail {props['name']!r} needs a LineString with two or more points")

        row = conn.execute(
            "SELECT id FROM mountains WHERE slug = %s", (props["mountain_slug"],)
        ).fetchone()
        if row is None:
            raise SystemExit(f"trail {props['name']!r} names unknown mountain {props['mountain_slug']!r}")
        if props["name"] in names_by_mountain[props["mountain_slug"]]:
            raise SystemExit(
                f"trail {props['name']!r} appears twice for {props['mountain_slug']!r}. "
                "Merge the lines or give each a distinct name."
            )

        conn.execute(
            """
            INSERT INTO trails (mountain_id, name, geom, length_km, elevation_gain_m)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (mountain_id, name) DO UPDATE SET
              geom = EXCLUDED.geom,
              length_km = EXCLUDED.length_km,
              elevation_gain_m = EXCLUDED.elevation_gain_m
            """,
            (row[0], props["name"], Jsonb(geometry), props.get("length_km"), props.get("elevation_gain_m")),
        )
        names_by_mountain[props["mountain_slug"]].append(props["name"])

    for slug, names in names_by_mountain.items():
        conn.execute(
            """
            DELETE FROM trails
            WHERE mountain_id = (SELECT id FROM mountains WHERE slug = %s)
              AND name <> ALL(%s::text[])
            """,
            (slug, names),
        )
    return len(collection["features"])


def load_trail_segments(conn: psycopg.Connection) -> int:
    """Upsert the mile-marked segments in trail_segments.geojson. Returns how many the file holds.

    A segment keeps its risk while its line and miles are unchanged; otherwise the risk
    clears until the next refresh scores it. Trails the file does not list lose their segments.
    """
    path = SEED_DIR / "trail_segments.geojson"
    features = json.loads(path.read_text(encoding="utf-8"))["features"] if path.exists() else []

    by_trail: dict[tuple[str, str], list[dict]] = {}
    for feature in features:
        props = feature["properties"]
        by_trail.setdefault((props["mountain_slug"], props["trail"]), []).append(feature)

    kept: list = []
    for (slug, name), segments in by_trail.items():
        row = conn.execute(
            "SELECT t.id FROM trails t JOIN mountains m ON m.id = t.mountain_id WHERE m.slug = %s AND t.name = %s",
            (slug, name),
        ).fetchone()
        if row is None:
            raise SystemExit(f"segments name trail {name!r} on {slug!r}, which trails.geojson does not have")
        trail_id = row[0]
        segments.sort(key=lambda f: f["properties"]["seq"])
        if [f["properties"]["seq"] for f in segments] != list(range(len(segments))):
            raise SystemExit(f"segments of {name!r} must be numbered 0, 1, 2, ... with no gaps")

        for feature in segments:
            props, geometry = feature["properties"], feature["geometry"]
            if geometry["type"] != "LineString" or props["end_mile"] <= props["start_mile"]:
                raise SystemExit(f"segment {props['seq']} of {name!r} needs a LineString and end_mile > start_mile")
            conn.execute(
                """
                INSERT INTO trail_segments (trail_id, seq, geom, start_mile, end_mile)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (trail_id, seq) DO UPDATE SET
                  geom = EXCLUDED.geom,
                  start_mile = EXCLUDED.start_mile,
                  end_mile = EXCLUDED.end_mile,
                  risk_level = CASE WHEN trail_segments.geom = EXCLUDED.geom
                                     AND trail_segments.start_mile = EXCLUDED.start_mile
                                     AND trail_segments.end_mile = EXCLUDED.end_mile
                                    THEN trail_segments.risk_level END,
                  probability = CASE WHEN trail_segments.geom = EXCLUDED.geom
                                      AND trail_segments.start_mile = EXCLUDED.start_mile
                                      AND trail_segments.end_mile = EXCLUDED.end_mile
                                     THEN trail_segments.probability END
                """,
                (trail_id, props["seq"], Jsonb(geometry), props["start_mile"], props["end_mile"]),
            )
        conn.execute("DELETE FROM trail_segments WHERE trail_id = %s AND seq >= %s", (trail_id, len(segments)))
        kept.append(trail_id)

    conn.execute("DELETE FROM trail_segments WHERE trail_id <> ALL(%s::uuid[])", (kept,))
    return len(features)


def main() -> None:
    with connect() as conn:
        load_mountains(conn)
        load_trails(conn)
        load_trail_segments(conn)
        rows = conn.execute(
            """
            SELECT m.slug, m.is_live, m.current_risk_level,
                   count(DISTINCT t.id) AS trails, count(s.id) AS segments
            FROM mountains m
            LEFT JOIN trails t ON t.mountain_id = m.id
            LEFT JOIN trail_segments s ON s.trail_id = t.id
            GROUP BY m.id ORDER BY m.is_live DESC, m.slug
            """
        ).fetchall()

    print(f"{len(rows)} mountains")
    for slug, is_live, risk, trails, segments in rows:
        print(f"  {slug:<15} {'live' if is_live else 'static':<6} risk={risk:<9} trails={trails:<3} segments={segments}")


if __name__ == "__main__":
    main()
