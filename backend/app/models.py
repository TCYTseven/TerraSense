"""API response models. frontend/lib/types.ts mirrors these. Change both together."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.domains import HazardDomain  # noqa: F401  (re-exported for the API models)
from app.risk import RiskLevel

PlaceKind = Literal["mountain", "hill"]

# Both domains' hazard types. app/domains.py is the single list; the hazards.type CHECK in
# schema.sql is generated from the same place, so the three never drift (step 34).
HazardType = Literal[
    "landslide", "debris_flow",
    "slab_avalanche", "loose_snow_avalanche", "wet_snow_avalanche",
]

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
    kind: PlaceKind = "mountain"
    # The regional LightGBM model's live answer at the summit, so the UI shows the model's
    # prediction rather than the seeded catalog color. model_input says what ground it scored:
    # Names the terrain window, e.g. regional_feature_stack or a hill-specific feature window.
    model_probability: float | None = None
    model_risk_level: RiskLevel | None = None
    model_method: str | None = None
    model_input: str | None = None
    # Esri World Imagery preview from mountain_satellite_images (Tiger seed), when present.
    satellite_image_url: str | None = None


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


class TrailRiskScore(BaseModel):
    """One trail on the saved 72-hour map: its worst point, and the terrain there."""

    trail_id: str
    name: str
    max_probability: float
    mean_probability: float
    share_high: float
    level: RiskLevel
    worst_point: list[float] | None  # lon, lat
    slope_deg: float | None
    factor: str | None


class OverallRisk(BaseModel):
    """The worst point on any mapped trail, and how much of the box is at high or above."""

    score: float
    level: RiskLevel
    trails_scored: int
    share_area_high: float
    area_mean: float | None


class MountainRiskSummary(BaseModel):
    """GET /mountains/{slug}/risk-summary: the mountain page's numbers, from the map the tiles show."""

    method: str
    scored_at: datetime
    overall: OverallRisk
    mean_slope_deg: float | None
    bbox: list[float] | None  # west, south, east, north
    threshold_72h_mm: float
    trails: list[TrailRiskScore]


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


class RiskEstimateCell(BaseModel):
    """The 1 km classifier cell around the point, on the same 30 m map."""

    size_m: int
    mean: float
    max: float
    share_high: float


class RiskEstimateRain(BaseModel):
    source: str
    as_of: datetime
    past_72h_mm: float
    next_72h_mm: float
    past_7d_mm: float
    threshold_72h_mm: float
    threshold_7d_mm: float


class RiskEstimateDriver(BaseModel):
    factor: Literal["terrain", "forecast_rain", "antecedent_moisture"]
    label: str
    detail: str
    logit_contribution: float
    effect: Literal["raises", "lowers", "neutral"]


class RiskEstimateValidation(BaseModel):
    """Held-out ROC-AUC behind the index, each with a 95% interval, from the ML artifacts."""

    terrain_roc_auc: float
    terrain_roc_auc_ci95: list[float]
    terrain_positives: int
    rainier_roc_auc: float
    rainier_roc_auc_ci95: list[float]
    rainier_positives: int
    rainier_slope_only_roc_auc: float
    trigger_roc_auc: float
    trigger_roc_auc_ci95: list[float]
    trigger_events: int
    trigger_storms: int
    trigger_years: list[int]


class RiskEstimate(BaseModel):
    """How the uncalibrated Model B risk index at this point was made."""

    method: str
    calibrated: Literal[False]
    unit: str
    pixel_probability: float | None
    susceptibility: float | None
    cell: RiskEstimateCell | None
    rain: RiskEstimateRain | None
    drivers: list[RiskEstimateDriver]
    validation: RiskEstimateValidation | None


class LandslideRiskPrediction(BaseModel):
    """Fail-closed, calibrated 72-hour rainfall-triggered landslide prediction.

    `state` belongs to the calibrated classifier alone. `probability` is the number to show: the
    calibrated one when it exists, else the Model B estimate the heat map is drawn from.
    """

    location: dict[str, float]
    prediction_window: dict[str, datetime]
    state: Literal["HIGH_RISK", "NOT_HIGH_RISK", "UNCERTAIN"]
    probability: float | None = Field(default=None, ge=0, le=1)
    probability_source: Literal["calibrated_classifier", "model_b_estimate"] | None = None
    probability_floor_applied: bool = False
    probability_floor: float = Field(default=0.1, ge=0.1, le=1)
    risk_level: RiskLevel | None = None
    estimate: RiskEstimate | None = None
    calibrated_probability: float | None
    high_risk_threshold: float | None
    confidence: RiskConfidence
    data_quality_score: float
    ood_score: float | None
    reason_codes: list[str]
    drivers: list[RiskDriver]
    data_sources: dict[str, Any]
    model: dict[str, Any]


class AvalancheRiskPrediction(BaseModel):
    """Fail-closed, calibrated next-24-hour avalanche prediction."""

    location: dict[str, float]
    prediction_window: dict[str, datetime]
    state: Literal["HIGH_RISK", "NOT_HIGH_RISK", "UNCERTAIN"]
    probability: float | None = Field(default=None, ge=0, le=1)
    calibrated_probability: float | None = Field(default=None, ge=0, le=1)
    probability_floor_applied: bool = False
    probability_floor: float = Field(default=0.1, ge=0.1, le=1)
    high_risk_threshold: float | None = Field(default=None, ge=0, le=1)
    confidence: RiskConfidence
    data_quality_score: float = Field(ge=0, le=1)
    ood_score: float | None = Field(default=None, ge=0, le=1)
    reason_codes: list[str]
    drivers: list[dict[str, Any]]
    snowpack: dict[str, Any]
    data_sources: dict[str, Any]
    model: dict[str, Any]
