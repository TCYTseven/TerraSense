"""Mountain reads for the globe and the mountain page."""

from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from psycopg.rows import DictRow

from app.db import get_conn
from app.history import historical_events
from app.mountain_catalog import ensure_catalog, sync_catalog
from app.ml.tiles import layer_url_path, read_metadata, slug_tiles_dir
from app.models import Hazard, LayerTiles, Mountain, MountainDetail, MountainRiskSummary, Trail, TrailSegment
from app.risk_summary import risk_summary
from app.runs import registry

router = APIRouter(prefix="/mountains", tags=["mountains"])

Conn = Annotated[psycopg.Connection[DictRow], Depends(get_conn)]

# Raster layers the map can request: the static susceptibility map (step 13) and the
# 72-hour probability heat map (step 18).
LAYERS = ("susceptibility", "probability")

RENDER_HINT = {
    "susceptibility": "Run ml/scripts/render_tiles.py [--mountain SLUG].",
    "probability": "Run Analyze now, or python -m app.assessment --save from backend/.",
}

MOUNTAIN_COLUMNS = """
    id, name, slug, lat, lon, elevation_m, region,
    current_risk_level, last_analyzed_at, is_live
"""


class CatalogSyncResponse(BaseModel):
    count: int
    source: str


@router.post("/catalog/sync", response_model=CatalogSyncResponse)
def sync_mountain_catalog(conn: Conn) -> CatalogSyncResponse:
    """Reload data/seed/mountains.json into Postgres. Does not call Wikidata or Overpass."""
    count, source = sync_catalog(conn)
    conn.commit()
    if count == 0:
        raise HTTPException(
            status_code=503,
            detail="No mountains in the database. Add data/seed/mountains.json and run python -m app.seed.",
        )
    return CatalogSyncResponse(count=count, source=source)


@router.get("")
def list_mountains(conn: Conn) -> list[Mountain]:
    """Every mountain for the globe, live ones first. Static mountains carry their seed risk."""
    ensure_catalog(conn)
    conn.commit()
    rows = conn.execute(
        f"SELECT {MOUNTAIN_COLUMNS} FROM mountains ORDER BY is_live DESC, name"
    ).fetchall()
    return [Mountain(**row) for row in rows]


@router.get("/{slug}")
def get_mountain(slug: str, conn: Conn) -> MountainDetail:
    """One mountain with its trails, their segments, its latest hazard, and past landslides."""
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
        SELECT h.id, h.run_id, h.type, h.severity, h.probability, h.confidence, h.geom, h.drivers,
               h.what, h.why, h.how_to_avoid, h.needs_review, h.created_at,
               h.trail_id, t.name AS trail_name, h.start_mile, h.end_mile, h.bypass
        FROM hazards h LEFT JOIN trails t ON t.id = h.trail_id
        WHERE h.mountain_id = %s ORDER BY h.created_at DESC LIMIT 1
        """,
        (mountain["id"],),
    ).fetchone()

    return MountainDetail(
        **mountain,
        trails=[Trail(**row, segments=segments_by_trail[row["id"]]) for row in trail_rows],
        active_hazard=Hazard(**hazard) if hazard else None,
        historical_events=historical_events(slug),
        active_run_id=running.id if (running := registry.active_run(slug)) and running.status == "running" else None,
    )


@router.get("/{slug}/risk-summary")
def get_risk_summary(slug: str, conn: Conn) -> MountainRiskSummary:
    """The overall score, mean slope, and top five trails, scored on the map the heat layer shows."""
    mountain = conn.execute("SELECT is_live FROM mountains WHERE slug = %s", (slug,)).fetchone()
    if mountain is None:
        raise HTTPException(status_code=404, detail=f"No mountain with slug {slug!r}")
    if not mountain["is_live"]:
        raise HTTPException(status_code=404, detail=f"{slug!r} is a static marker and is not scored")
    summary = risk_summary(conn, slug)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"No saved probability map yet. {RENDER_HINT['probability']}")
    return MountainRiskSummary(**summary)


@router.get("/{slug}/layers/{layer}")
def get_layer(slug: str, layer: str, request: Request, conn: Conn) -> LayerTiles:
    """The tile URL template for one raster layer. Only live mountains have layers."""
    mountain = conn.execute("SELECT is_live FROM mountains WHERE slug = %s", (slug,)).fetchone()
    if mountain is None:
        raise HTTPException(status_code=404, detail=f"No mountain with slug {slug!r}")
    if not mountain["is_live"]:
        raise HTTPException(status_code=404, detail=f"{slug!r} is a static marker and has no map layers")
    if layer not in LAYERS:
        raise HTTPException(status_code=404, detail=f"Unknown layer {layer!r}. Layers: {', '.join(LAYERS)}")
    metadata = read_metadata(layer, tiles_dir=slug_tiles_dir(slug))
    if metadata is None:
        raise HTTPException(status_code=404, detail=f"Layer {layer!r} is not rendered yet. {RENDER_HINT[layer]}")

    # The version query makes browsers drop cached tiles after a re-render.
    base = str(request.base_url).rstrip("/")
    return LayerTiles(
        layer=layer,
        tiles=f"{base}/tiles/{layer_url_path(slug, layer)}/{{z}}/{{x}}/{{y}}.png?v={metadata['version']}",
        bounds=metadata["bounds"],
        minzoom=metadata["minzoom"],
        maxzoom=metadata["maxzoom"],
        method=metadata.get("method"),
        updated_at=metadata["created_at"],
    )
