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
/** GET /forecast (step 25): the hiker card's facts from the latest finished run. */
export interface Forecast {
  mountain_slug: string;
  run_id: string;
  hazard_id: string;
  trail_id: string | null;
  trail_name: string | null;
  level: RiskLevel;
  /** The Alert Writer's hiker sentence. */
  sentence: string;
  start_mile: number | null;
  end_mile: number | null;
  /** Added distance and climb come from here, never from the model's text. */
  bypass: Bypass | null;
}

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
  /** The run going right now, so a page that opens mid-run can follow it (step 22). */
  active_run_id: string | null;
}

/** One trail on the saved 72-hour map: its worst point, and the terrain there. */
export interface TrailRiskScore {
  trail_id: string;
  name: string;
  max_probability: number;
  mean_probability: number;
  share_high: number;
  level: RiskLevel;
  /** [lon, lat] */
  worst_point: Position | null;
  slope_deg: number | null;
  factor: string | null;
}

/** GET /mountains/{slug}/risk-summary: the hill card's numbers, from the map the heat layer shows. */
export interface MountainRiskSummary {
  method: string;
  scored_at: string;
  /** The worst point on any mapped trail, and how much of the box is at high or above. */
  overall: {
    score: number;
    level: RiskLevel;
    trails_scored: number;
    share_area_high: number;
    area_mean: number | null;
  };
  mean_slope_deg: number | null;
  /** [west, south, east, north] */
  bbox: [number, number, number, number] | null;
  threshold_72h_mm: number;
  /** The five most exposed trails, worst first. */
  trails: TrailRiskScore[];
}

export type LandslideRiskState = "HIGH_RISK" | "NOT_HIGH_RISK" | "UNCERTAIN";

export type RiskProbabilitySource = "calibrated_classifier" | "model_b_estimate";

export interface RiskEstimateDriver {
  factor: "terrain" | "forecast_rain" | "antecedent_moisture";
  label: string;
  detail: string;
  logit_contribution: number;
  effect: "raises" | "lowers" | "neutral";
}

/** Held-out ROC-AUC behind the index, each with a 95% interval, from the ML artifacts. */
export interface RiskEstimateValidation {
  terrain_roc_auc: number;
  terrain_roc_auc_ci95: [number, number];
  terrain_positives: number;
  rainier_roc_auc: number;
  rainier_roc_auc_ci95: [number, number];
  rainier_positives: number;
  trigger_roc_auc: number;
  trigger_roc_auc_ci95: [number, number];
  trigger_events: number;
  trigger_storms: number;
  trigger_years: [number, number];
}

/** How the uncalibrated Model B risk index at the point was made. */
export interface RiskEstimate {
  method: string;
  calibrated: false;
  unit: string;
  pixel_probability: number | null;
  susceptibility: number | null;
  /** The 1 km classifier cell around the point, on the same 30 m map. */
  cell: { size_m: number; mean: number; max: number; share_high: number } | null;
  rain: {
    source: string;
    as_of: string;
    past_72h_mm: number;
    next_72h_mm: number;
    past_7d_mm: number;
    threshold_72h_mm: number;
    threshold_7d_mm: number;
  } | null;
  drivers: RiskEstimateDriver[];
  validation: RiskEstimateValidation | null;
}

/**
 * `state` belongs to the calibrated classifier alone. `probability` is the number to show: the
 * calibrated one when it exists, else the Model B estimate the heat map is drawn from.
 */
export interface LandslideRiskPrediction {
  location: { latitude: number; longitude: number };
  prediction_window: { start: string; end: string };
  state: LandslideRiskState;
  probability: number | null;
  probability_source: RiskProbabilitySource | null;
  risk_level: RiskLevel | null;
  estimate: RiskEstimate | null;
  calibrated_probability: number | null;
  high_risk_threshold: number | null;
  confidence: { lower: number | null; upper: number | null };
  data_quality_score: number;
  ood_score: number | null;
  reason_codes: string[];
  drivers: { feature: string; value: number | null; importance: number; direction: "model risk driver" }[];
  data_sources: Record<string, unknown>;
  model: Record<string, unknown>;
}

/**
 * Panel order. The first five are analysts: the backend fans them out together in one
 * asyncio.gather, so several rows can be "running" at once. The Risk Synthesizer waits for all
 * five, and the Alert Writer waits for the Synthesizer.
 */
export const AGENT_NAMES = ["terrain", "weather", "trail", "history", "routes", "synthesizer", "writer"] as const;
export type AgentName = (typeof AGENT_NAMES)[number];

/** The agents that run in parallel. None of them reads another's answer. */
export const ANALYST_NAMES = ["terrain", "weather", "trail", "history", "routes"] as const;

export const AGENT_STATUSES = ["waiting", "running", "done", "error"] as const;
export type AgentStatus = (typeof AGENT_STATUSES)[number];

export const PROVIDER_NAMES = ["gemini", "grok"] as const;
/** The two LLM providers the router picks between. */
export type ProviderName = (typeof PROVIDER_NAMES)[number];

/** One rule the router checked, and the provider it pointed to (null when it changed nothing). */
export interface RouteRule {
  rule: string;
  verdict: ProviderName | null;
  detail: string;
}

/** Why an agent's call went to Gemini Flash or Grok. */
export interface RouteDecision {
  provider: ProviderName;
  model: string;
  /** "Gemini 3.8 Flash", "Grok 4.7". */
  label: string;
  tier: "fast" | "strong";
  /** One sentence. */
  reason: string;
  rules: RouteRule[];
  /** Tried in order if the chosen provider fails. */
  fallback: ProviderName[];
  available: Record<string, boolean>;
}

/** A tool the agent's code ran before its model call. Tools return precomputed facts. */
export interface ToolCall {
  name: string;
  args: Record<string, unknown>;
  result: unknown;
  ms: number;
}

export interface Attempt {
  provider: ProviderName;
  model: string;
  ok: boolean;
  latency_ms: number;
  error: string | null;
  /** This call re-asked the model after its answer failed a check. */
  repair: boolean;
}

export interface Usage {
  input_tokens: number | null;
  output_tokens: number | null;
  reasoning_tokens: number | null;
}

/** Everything the reasoning panel shows for one agent. */
export interface AgentTrace {
  route: RouteDecision;
  tools: ToolCall[];
  attempts: Attempt[];
  /** The provider's own reasoning summary, when it returns one. */
  thoughts: string[];
  /** The steps the agent gave in its JSON. */
  reasoning: string[];
  /** What the code did with the answer: merges, clamps, overrides, fallbacks. */
  checks: string[];
  /** The model's validated JSON, before the code merged facts into the payload. */
  output: Record<string, unknown> | null;
  usage: Usage | null;
  started_at: string | null;
  finished_at: string | null;
  latency_ms: number | null;
}

/** One message on WS /runs/{run_id}/stream: an agent started, finished, or failed. */
export interface AgentEvent {
  run_id: string;
  agent: AgentName;
  status: AgentStatus;
  summary: string;
  payload: Record<string, unknown>;
  /** The router's decision, tool calls, and reasoning (step 20). Absent on fixtures. */
  trace?: AgentTrace | null;
}

export const RUN_STATUSES = ["running", "done", "error"] as const;
export type RunStatus = (typeof RUN_STATUSES)[number];
export type RunPhase = "starting" | "scoring" | "agents" | "saving" | "finished";

/** The panel's rain lines, from the run's Open-Meteo fetch. */
export interface RainTotals {
  /** "open-meteo", or "fixture" for a saved test storm. */
  source: string;
  as_of: string;
  past_72h_mm: number;
  next_24h_mm: number;
}

/** GET /runs/{run_id}, and the snapshot a stream sends on connect and at each phase (step 22). */
export interface Run {
  id: string;
  mountain_slug: string;
  status: RunStatus;
  phase: RunPhase;
  /** The status line under the agent rows. */
  message: string;
  started_at: string;
  finished_at: string | null;
  elapsed_s: number | null;
  /** The latest event per agent. An agent not listed is waiting. */
  agents: Partial<Record<AgentName, AgentEvent>>;
  hazard_id: string | null;
  severity: RiskLevel | null;
  needs_review: boolean | null;
  /** How the heat map was made, such as "susceptibility stand-in (Model B pending)". */
  method: string | null;
  rain: RainTotals | null;
  error: string | null;
  failed_agent: AgentName | null;
  /** The run's whole conclusion. Null until the Alert Writer finishes, and on a failed run. */
  advisory: Advisory | null;
}


/**
 * The advisory: everything one run concluded, in one object. It rides on the Run, and
 * GET /runs/{id}/advisory and GET /mountains/{slug}/advisory return it on its own.
 *
 * Every field is either a fact the backend computed or a sentence an agent wrote about those
 * facts. The route numbers, miles, and levels are the map's, never a model's, so they are safe
 * to render as data.
 */

/** Quietest to loudest. How loudly the park is speaking today. */
export const POSTURES = ["all_clear", "watch", "advisory", "warning", "evacuate"] as const;
export type Posture = (typeof POSTURES)[number];

/** How fast rangers have to act. */
export const PRIORITIES = ["routine", "elevated", "urgent", "emergency"] as const;
export type Priority = (typeof PRIORITIES)[number];

/** How the park tells people. The newsletter is the quietest; the broadcast is an evacuation only. */
export type Channel =
  | "newsletter"
  | "website_banner"
  | "trailhead_signage"
  | "visitor_center_briefing"
  | "ranger_radio"
  | "social_media"
  | "press_release"
  | "emergency_broadcast";

/** One route on the avoid or the safe list, with the catalog numbers behind it. */
export interface AdvisoryRoute {
  trail: string;
  level: RiskLevel;
  max_probability: number;
  /** Share of the walk at high or above: one bad switchback reads differently from a bad trail. */
  share_at_high: number;
  length_mi: number | null;
  elevation_gain_ft: number | null;
  crosses_hazard_zone: boolean;
  km_to_hazard_zone: number | null;
  is_hero_trail: boolean;
  /** The agent's sentence, citing the numbers above. */
  reason: string;
  /** Where to go instead (avoid), or the day's caution (safe). */
  guidance: string;
}

/** What the park does about it, scaled to the hazard. */
export interface AdvisoryResponse {
  posture: Posture;
  /** 0 all_clear to 4 evacuate, so a component can sort or color without a lookup. */
  posture_rank: number;
  priority: Priority;
  /** 0 routine to 3 emergency. */
  priority_rank: number;
  recommended_action: "monitor" | "close";
  headline: string;
  channels: Channel[];
  actions: string[];
  staffing: string;
  timeline: string;
  escalate_if: string;
}

/** The zone the advisory is about. Null when no mile of the hero trail reaches high. */
export interface AdvisoryHazard {
  type: HazardType;
  severity: RiskLevel;
  place: string;
  max_probability: number;
  area_km2: number | null;
  drivers: string[];
  trail: string | null;
  start_mile: number | null;
  end_mile: number | null;
  bypass_name: string | null;
  bypass_added_mi: number | null;
  bypass_added_ft: number | null;
}

/** The weather the agents read. Null fields mean this run's source lacked that series. */
export interface AdvisoryConditions {
  source: string;
  as_of: string;
  rain_past_72h_mm: number;
  rain_next_24h_mm: number;
  rain_past_72h_in: number;
  rain_next_24h_in: number;
  temp_now_c: number | null;
  temp_min_next_72h_c: number | null;
  temp_max_next_72h_c: number | null;
  freeze_thaw_cycles_next_72h: number | null;
  snowfall_next_72h_cm: number | null;
  wind_max_next_24h_kmh: number | null;
  soil_moisture_now: number | null;
  freezing_level_now_m: number | null;
}

/** The ML prediction the agents treated as their source of truth. */
export interface AdvisoryModel {
  method: string;
  is_stand_in: boolean;
  note: string;
  map_max: number | null;
  map_mean: number | null;
  share_at_high: number | null;
}

/** One agent's rating, so the panel can show where the agents agreed. */
export interface AgentVerdict {
  label: string;
  severity: RiskLevel | null;
  confidence: number | null;
  provider: ProviderName | null;
  model: string | null;
  latency_ms: number | null;
}

/** The Alert Writer's copy, for the panel and the hiker card. */
export interface AdvisoryAlert {
  title: string;
  body: string;
  hiker: string;
  what: string;
  why: string;
  how_to_avoid: string;
}

export interface Advisory {
  run_id: string;
  mountain_slug: string;
  mountain: string;
  generated_at: string;
  severity: RiskLevel;
  confidence: number;
  needs_review: boolean;
  summary: string;
  /** A paragraph for the reasoning panel: where the analysts agreed and where they did not. */
  analysis: string;
  hazard: AdvisoryHazard | null;
  /** Exactly three routes to keep hikers off today, worst first. */
  avoid: AdvisoryRoute[];
  /** Exactly three routes that are safest today, best first. */
  safe: AdvisoryRoute[];
  response: AdvisoryResponse;
  conditions: AdvisoryConditions | null;
  model: AdvisoryModel;
  alert: AdvisoryAlert;
  agents: Partial<Record<AgentName, AgentVerdict>>;
  /** What the backend changed or refused in the agents' answers, for the reasoning panel. */
  checks: string[];
}

/** A stream message about the run as a whole. Agent messages are plain AgentEvents. */
export interface RunUpdate {
  kind: "run";
  run: Run;
}

/** One slope the runout can start from. Rank 1 is the route most likely to fail. */
export interface PressurePoint {
  id: string;
  rank: number;
  level: RiskLevel;
  peak: number;
  lon: number;
  lat: number;
  polygon: Polygon;
  facing: string;
  elevation_m: number | null;
  drivers: string[];
  trail_id: string | null;
  trail_name: string | null;
  start_mile: number | null;
  end_mile: number | null;
}

export interface FlowFeatureCollection {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    properties: { level: RiskLevel; intensity: number };
    geometry: Polygon;
  }>;
}

export interface RunoutFrame {
  index: number;
  t_s: number;
  geojson: FlowFeatureCollection;
}

export interface RunoutStep {
  id: string;
  kind: "release" | "channel" | "trail" | "stop";
  title: string;
  t_s: number;
  lon: number;
  lat: number;
  distance_m: number | null;
  drop_m: number | null;
  trail_name: string | null;
  start_mile: number | null;
  end_mile: number | null;
  level: RiskLevel | null;
}

export interface SimulationCallout {
  id: string;
  step_id: string;
  audience: "rangers" | "public";
  text: string;
  t_s: number;
}

/** An illustrative debris-flow runout. Times are simulated seconds, not a forecast. */
export interface Simulation {
  id: string;
  mountain_slug: string;
  status: "running" | "done" | "error";
  method: string;
  source: "dem" | "trail";
  pressure_point: PressurePoint | null;
  duration_s: number;
  distance_m: number;
  drop_m: number;
  frames: RunoutFrame[];
  steps: RunoutStep[];
  callouts: SimulationCallout[];
  callouts_from_templates: boolean;
  error: string | null;
}
