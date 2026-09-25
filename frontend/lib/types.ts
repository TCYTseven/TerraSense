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
}

/** GET /mountains/{slug}. */
export interface MountainDetail extends Mountain {
  trails: Trail[];
  active_hazard: Hazard | null;
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
