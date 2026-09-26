"""API response models. frontend/lib/types.ts mirrors these. Change both together."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

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


class BypassPiece(BaseModel):
    """One edge of a bypass, with its own risk, so the map colors the detour by level."""

    trail: str | None  # null for an unnamed connector path
    probability: float
    level: RiskLevel
    geom: Geometry  # LineString


class Bypass(BaseModel):
    """The detour around a hazard's miles (step 19). Every meter is a mapped trail."""

    name: str
    via: list[str]
    leaves_at_mile: float
    rejoins_at_mile: float
    length_km: float
    replaced_km: float
    added_km: float  # negative when the detour is shorter than the miles it replaces
    added_elevation_m: int  # climb on the detour minus climb on the miles it replaces
    max_probability: float
    level: RiskLevel
    geom: Geometry  # LineString, in walking order
    pieces: list[BypassPiece]


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
    bypass: Bypass | None  # step 19; null when no trail runs around the miles


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
    # The run going right now, so a page that opens mid-run can follow it (step 22).
    active_run_id: str | None


class RiskPredictionRequest(BaseModel):
    """A point in the configurable prediction grid; the default cell is 1 km."""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timestamp: datetime | None = None


class RiskConfidence(BaseModel):
    lower: float | None
    upper: float | None


class RiskDriver(BaseModel):
    feature: str
    value: float | None
    importance: float
    direction: Literal["model risk driver"]


class LandslideRiskPrediction(BaseModel):
    """Fail-closed, calibrated 72-hour rainfall-triggered landslide prediction."""

    location: dict[str, float]
    prediction_window: dict[str, datetime]
    state: Literal["HIGH_RISK", "NOT_HIGH_RISK", "UNCERTAIN"]
    calibrated_probability: float | None
    high_risk_threshold: float | None
    confidence: RiskConfidence
    data_quality_score: float
    ood_score: float | None
    reason_codes: list[str]
    drivers: list[RiskDriver]
    data_sources: dict[str, Any]
    model: dict[str, Any]


class TrailRiskEntry(BaseModel):
    """One of the most exposed trails on the current map. Every number is read off the map."""

    trail_id: UUID
    name: str
    score: float  # the worst probability on the tread
    mean_probability: float
    share_high: float  # share of the walk at high or above
    level: RiskLevel
    point: list[float] | None  # [lon, lat] of the worst point: where the marker sits
    slope_deg: float | None  # hillside slope at that point, None without the terrain stack
    primary_factor: str  # the terrain factor at that point, in plain words
    length_mi: float | None


class TrailRiskView(BaseModel):
    """GET /mountains/{slug}/trail-risk: the hill card's trail list, overall score, and measures."""

    mountain_slug: str
    method: str  # the map's method, "model b" or the stand-in label
    source: Literal["run", "preview"]  # the last run's published map, or a preview on current rain
    computed_at: datetime
    score: float  # the mean of the trails' scores
    level: RiskLevel
    map_mean: float | None
    map_share_high: float | None  # share of the map at high or above
    mean_slope_deg: float | None
    area_km2: float
    trails: list[TrailRiskEntry]
    preventative: list[str]
