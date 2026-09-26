"""Apply schema.sql to DATABASE_URL.

From backend/:
    python -m app.schema            create any missing tables
    python -m app.schema --reset    drop the six tables first, then recreate them
"""

import argparse
from pathlib import Path

from app.db import connect

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# Children before parents, so a reset drops in a valid order.
TABLES = [
    "alerts",
    "hazards",
    "analysis_runs",
    "trail_segments",
    "trails",
    "mountain_satellite_images",
    "mountains",
]


def apply_schema(reset: bool = False) -> list[str]:
    """Run schema.sql and return the TerraSense tables that now exist."""
    with connect() as conn:
        if reset:
            conn.execute(f"DROP TABLE IF EXISTS {', '.join(TABLES)} CASCADE")
        conn.execute(SCHEMA_PATH.read_text())
        rows = conn.execute(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = current_schema() AND table_name = ANY(%s)
            ORDER BY table_name
            """,
            (TABLES,),
        ).fetchall()
    return [name for (name,) in rows]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--reset", action="store_true", help="drop the six tables and their data first"
    )
    args = parser.parse_args()

    tables = apply_schema(reset=args.reset)
    print(f"{len(tables)} of {len(TABLES)} tables present: {', '.join(tables)}")
    if len(tables) != len(TABLES):
        raise SystemExit("schema is incomplete")


if __name__ == "__main__":
    main()
