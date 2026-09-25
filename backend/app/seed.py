"""Load data/seed/ into Postgres. From backend/: python -m app.seed

Mountains upsert by slug. Trails upsert by (mountain, name), and a mountain's
trails that are no longer in the file are removed. Re-running is safe.
"""

import json

import psycopg
from psycopg.types.json import Jsonb

from app.config import REPO_ROOT
from app.db import connect

SEED_DIR = REPO_ROOT / "data" / "seed"


def load_mountains(conn: psycopg.Connection) -> int:
    """Upsert every mountain in mountains.json. Returns how many the file holds."""
    mountains = json.loads((SEED_DIR / "mountains.json").read_text(encoding="utf-8"))
    for mountain in mountains:
        # The seed risk is a placeholder until the mountain's first real analysis.
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


def main() -> None:
    with connect() as conn:
        load_mountains(conn)
        load_trails(conn)
        rows = conn.execute(
            """
            SELECT m.slug, m.is_live, m.current_risk_level, count(t.id) AS trails
            FROM mountains m LEFT JOIN trails t ON t.mountain_id = m.id
            GROUP BY m.id ORDER BY m.is_live DESC, m.slug
            """
        ).fetchall()

    print(f"{len(rows)} mountains")
    for slug, is_live, risk, trails in rows:
        print(f"  {slug:<15} {'live' if is_live else 'static':<6} risk={risk:<9} trails={trails}")


if __name__ == "__main__":
    main()
