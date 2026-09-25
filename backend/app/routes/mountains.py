"""Mountain reads for the globe and the mountain page."""

from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from psycopg.rows import DictRow

from app.db import get_conn
from app.models import Hazard, Mountain, MountainDetail, Trail, TrailSegment

router = APIRouter(prefix="/mountains", tags=["mountains"])

Conn = Annotated[psycopg.Connection[DictRow], Depends(get_conn)]

MOUNTAIN_COLUMNS = """
    id, name, slug, lat, lon, elevation_m, region,
    current_risk_level, last_analyzed_at, is_live
"""


@router.get("")
def list_mountains(conn: Conn) -> list[Mountain]:
    """Every mountain for the globe, live ones first. Static mountains carry their seed risk."""
    rows = conn.execute(
        f"SELECT {MOUNTAIN_COLUMNS} FROM mountains ORDER BY is_live DESC, name"
    ).fetchall()
    return [Mountain(**row) for row in rows]


@router.get("/{slug}")
def get_mountain(slug: str, conn: Conn) -> MountainDetail:
    """One mountain with its trails, their segments, and its latest hazard if one exists."""
    mountain = conn.execute(
        f"SELECT {MOUNTAIN_COLUMNS} FROM mountains WHERE slug = %s", (slug,)
    ).fetchone()
    if mountain is None:
        raise HTTPException(status_code=404, detail=f"No mountain with slug {slug!r}")

    trail_rows = conn.execute(
        """
        SELECT id, name, geom, length_km, elevation_gain_m
        FROM trails WHERE mountain_id = %s ORDER BY name
        """,
        (mountain["id"],),
    ).fetchall()

    segments_by_trail: dict = {row["id"]: [] for row in trail_rows}
    segment_rows = conn.execute(
        """
        SELECT trail_id, id, seq, geom, start_mile, end_mile, risk_level, probability
        FROM trail_segments WHERE trail_id = ANY(%s) ORDER BY trail_id, seq
        """,
        (list(segments_by_trail),),
    ).fetchall()
    for row in segment_rows:
        segments_by_trail[row.pop("trail_id")].append(TrailSegment(**row))

    hazard = conn.execute(
        """
        SELECT id, run_id, type, severity, probability, confidence, geom, drivers,
               what, why, how_to_avoid, needs_review, created_at
        FROM hazards WHERE mountain_id = %s ORDER BY created_at DESC LIMIT 1
        """,
        (mountain["id"],),
    ).fetchone()

    return MountainDetail(
        **mountain,
        trails=[Trail(**row, segments=segments_by_trail[row["id"]]) for row in trail_rows],
        active_hazard=Hazard(**hazard) if hazard else None,
    )
