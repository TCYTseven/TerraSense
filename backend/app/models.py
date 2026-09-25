"""API response models. frontend/lib/types.ts mirrors these. Change both together."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

RiskLevel = Literal["low", "moderate", "high", "extreme"]
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


class MountainDetail(Mountain):
    trails: list[Trail]
    active_hazard: Hazard | None
