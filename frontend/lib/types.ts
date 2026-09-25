/**
 * Shapes shared with the API. They mirror backend/app/models.py. Change both together.
 * IDs are UUID strings. Times are ISO 8601 strings with a timezone.
 */

export const RISK_LEVELS = ["low", "moderate", "high", "extreme"] as const;
export type RiskLevel = (typeof RISK_LEVELS)[number];

export type HazardType = "landslide" | "debris_flow";

/** A GeoJSON position: [longitude, latitude]. */
export type Position = [number, number];

export interface LineString {
  type: "LineString";
  coordinates: Position[];
}

export interface Polygon {
  type: "Polygon";
  coordinates: Position[][];
}

export interface Mountain {
  id: string;
  name: string;
  slug: string;
  lat: number;
  lon: number;
  elevation_m: number;
  region: string;
  current_risk_level: RiskLevel;
  last_analyzed_at: string | null;
  is_live: boolean;
}

export interface TrailSegment {
  id: string;
  seq: number;
  geom: LineString;
  start_mile: number;
  end_mile: number;
  risk_level: RiskLevel | null;
  probability: number | null;
}

export interface Trail {
  id: string;
  name: string;
  geom: LineString;
  length_km: number | null;
  elevation_gain_m: number | null;
  segments: TrailSegment[];
}

/** One edge of a bypass with its own risk, so the map colors the detour by level. */
export interface BypassPiece {
  /** Null for an unnamed connector path. */
  trail: string | null;
  probability: number;
  level: RiskLevel;
  geom: LineString;
}

/** The detour around a hazard's miles (step 19). Every meter is a mapped trail. */
export interface Bypass {
  name: string;
  via: string[];
  leaves_at_mile: number;
  rejoins_at_mile: number;
  length_km: number;
  replaced_km: number;
  /** Negative when the detour is shorter than the miles it replaces. */
  added_km: number;
  /** Climb on the detour minus climb on the miles it replaces. */
  added_elevation_m: number;
  max_probability: number;
  level: RiskLevel;
  /** In walking order. */
  geom: LineString;
  pieces: BypassPiece[];
}

export interface Hazard {
  id: string;
  run_id: string | null;
  type: HazardType;
  severity: RiskLevel;
  probability: number;
  confidence: number | null;
  geom: Polygon;
  drivers: string[];
  what: string | null;
  why: string | null;
  how_to_avoid: string | null;
  needs_review: boolean;
  created_at: string;
  /** The hero trail miles the zone covers (step 18). Null on hazards saved before them. */
  trail_id: string | null;
  trail_name: string | null;
  start_mile: number | null;
  end_mile: number | null;
  /** Step 19. Null when no trail runs around the miles: the advice is to turn back. */
  bypass: Bypass | null;
}

/** GET /mountains/{slug}/layers/{layer}: a raster layer served as XYZ tiles. */
export interface LayerTiles {
  layer: string;
  /** URL template with {z}/{x}/{y}. */
  tiles: string;
  /** [west, south, east, north]. */
  bounds: [number, number, number, number];
  minzoom: number;
  maxzoom: number;
  /**
   * How the values were made, such as "knowledge-driven index", "lightgbm", "model b", or
   * "susceptibility stand-in (Model B pending)" while step 17 is out.
   */
  method: string | null;
  updated_at: string;
}

/** A past landslide from a catalog, drawn as a map pin. */
export interface HistoricalEvent {
  id: string;
  /** YYYY-MM-DD. */
  date: string | null;
  title: string | null;
  /** The catalog's type, such as "landslide" or "debris_flow". */
  category: string | null;
  trigger: string | null;
  /** "exact", "1km", ... "50km". */
  location_accuracy: string | null;
  source_name: string | null;
  source_link: string | null;
  catalog: string;
  lon: number;
  lat: number;
}

/** GET /mountains/{slug}. */
export interface MountainDetail extends Mountain {
  /** The hero trail is the one with segments: the model scores it mile by mile. */
  trails: Trail[];
  active_hazard: Hazard | null;
  /** Empty until the landslide catalog is downloaded (step 10). */
  historical_events: HistoricalEvent[];
}

export const AGENT_NAMES = ["terrain", "weather", "trail", "synthesizer", "writer"] as const;
export type AgentName = (typeof AGENT_NAMES)[number];

export const AGENT_STATUSES = ["waiting", "running", "done", "error"] as const;
export type AgentStatus = (typeof AGENT_STATUSES)[number];

/** One message on WS /runs/{run_id}/stream: an agent started, finished, or failed. */
export interface AgentEvent {
  run_id: string;
  agent: AgentName;
  status: AgentStatus;
  summary: string;
  payload: Record<string, unknown>;
}
