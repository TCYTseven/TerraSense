"""API response models. frontend/lib/types.ts mirrors these. Change both together."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

from app.risk import RiskLevel

HazardType = Literal["landslide", "debris_flow"]

# A GeoJSON geometry object, stored as-is in jsonb: {"type": ..., "coordinates": ...}
Geometry = dict[str, Any]


class Mountain(BaseModel):
    id: UUID
    name: str
    slug: str
    lat: float
    lon: float
    elevation_m: int
    region: str
    current_risk_level: RiskLevel
    last_analyzed_at: datetime | None
    is_live: bool


class TrailSegment(BaseModel):
    id: UUID
    seq: int
    geom: Geometry
    start_mile: float
    end_mile: float
    risk_level: RiskLevel | None
    probability: float | None


class Trail(BaseModel):
    id: UUID
    name: str
    geom: Geometry
    length_km: float | None
    elevation_gain_m: int | None
    segments: list[TrailSegment]


class Hazard(BaseModel):
    id: UUID
    run_id: UUID | None
    type: HazardType
    severity: RiskLevel
    probability: float
    confidence: float | None
    geom: Geometry
    drivers: list[str]
    what: str | None
    why: str | None
    how_to_avoid: str | None
    needs_review: bool
    created_at: datetime
    # The hero trail miles the zone covers (step 18). Null on hazards saved before them.
    trail_id: UUID | None
    trail_name: str | None
    start_mile: float | None
    end_mile: float | None


class LayerTiles(BaseModel):
    """A raster map layer served as XYZ tiles."""

    layer: str
    tiles: str  # URL template with {z}/{x}/{y}
    bounds: list[float]  # [west, south, east, north]
    minzoom: int
    maxzoom: int
    method: str | None  # how the values were made, e.g. "knowledge-driven index" or "lightgbm"
    updated_at: datetime


class HistoricalEvent(BaseModel):
    """A past landslide from a catalog, drawn as a map pin."""

    id: str
    date: str | None  # YYYY-MM-DD
    title: str | None
    category: str | None  # the catalog's type, such as "landslide" or "debris_flow"
    trigger: str | None
    location_accuracy: str | None  # "exact", "1km", ... "50km"
    source_name: str | None
    source_link: str | None
    catalog: str
    lon: float
    lat: float


class MountainDetail(Mountain):
    trails: list[Trail]
    active_hazard: Hazard | None
    historical_events: list[HistoricalEvent]
