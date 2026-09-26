"""On-demand XYZ tiles for catalog mountains (same raster path as Rainier susceptibility)."""

from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from psycopg.rows import DictRow

from app.db import get_conn
from app.ml.synthetic_heatmap import render_synthetic_tile

router = APIRouter(tags=["tiles"])
Conn = Annotated[psycopg.Connection[DictRow], Depends(get_conn)]


@router.get("/tiles/synthetic/{slug}/{z}/{x}/{y}.png")
def synthetic_tile(slug: str, z: int, x: int, y: int, conn: Conn) -> Response:
    """Procedural susceptibility-colored tile for peaks without offline-rendered layers."""
    row = conn.execute(
        "SELECT slug, lat, lon, elevation_m, is_live FROM mountains WHERE slug = %s",
        (slug,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"No mountain with slug {slug!r}")
    if row["is_live"]:
        raise HTTPException(
            status_code=404,
            detail=f"{slug!r} uses rendered tiles under /tiles/susceptibility/, not synthetic.",
        )
    if z < 0 or z > 22:
        raise HTTPException(status_code=404, detail="Zoom out of range")
    body = render_synthetic_tile(slug, row["lon"], row["lat"], row["elevation_m"], z, x, y)
    return Response(content=body, media_type="image/png")
