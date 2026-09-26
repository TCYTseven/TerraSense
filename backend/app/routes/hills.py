"""Hill reads. Same detail shape as a mountain, only for kind = hill."""

from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.rows import DictRow

from app.db import get_conn
from app.models import LayerTiles, MountainDetail, MountainRiskSummary
from app.routes import mountains as mountain_routes

router = APIRouter(prefix="/hills", tags=["hills"])

Conn = Annotated[psycopg.Connection[DictRow], Depends(get_conn)]


def require_hill(slug: str, conn: psycopg.Connection[DictRow]) -> None:
    """404 unless this slug is a seeded hill. A mountain slug is not a hill."""
    row = conn.execute("SELECT kind FROM mountains WHERE slug = %s", (slug,)).fetchone()
    if row is None or row["kind"] != "hill":
        raise HTTPException(status_code=404, detail=f"No hill with slug {slug!r}")


@router.get("/{slug}", response_model=MountainDetail)
def get_hill(slug: str, conn: Conn) -> MountainDetail:
    require_hill(slug, conn)
    return mountain_routes.get_mountain(slug, conn)


@router.get("/{slug}/risk-summary", response_model=MountainRiskSummary)
def get_hill_risk_summary(slug: str, conn: Conn) -> MountainRiskSummary:
    require_hill(slug, conn)
    return mountain_routes.get_risk_summary(slug, conn)


@router.get("/{slug}/layers/{layer}", response_model=LayerTiles)
def get_hill_layer(slug: str, layer: str, request: Request, conn: Conn) -> LayerTiles:
    require_hill(slug, conn)
    return mountain_routes.get_layer(slug, layer, request, conn)
