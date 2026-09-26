/**
 * The mountain page's view model: what the mountain page renders, independent of where the
 * numbers come from. `lib/mountain-view-build.ts` fills it from the mountain and the risk summary, which
 * scores every trail on the saved one-week map.
 */

import type { LineString, Position, RiskLevel } from "./types";

export const TRAIL_LETTERS = ["A", "B", "C", "D", "E"] as const;
export type TrailLetter = (typeof TRAIL_LETTERS)[number];

/** One of the five most at-risk trails, with the region its marker sits on. */
export interface TrailRisk {
  id: string;
  /** A for the riskiest, E for the fifth. The panel row and the map marker share it. */
  letter: TrailLetter;
  name: string;
  /** 0 to 1. The level follows the shared bins. */
  score: number;
  level: RiskLevel;
  /** Hillside slope at the riskiest point, in degrees. Null without the terrain stack. */
  slopeDeg: number | null;
  /** The leading terrain factor at the riskiest point ("Drainage channel"). Null without the terrain stack. */
  primaryFactor: string | null;
  /** Where the marker sits and where "View" centers the camera. */
  center: Position;
  /** The camera zoom "View" flies to. */
  zoom: number;
  /** The trail line, when the mountain's trails include it. */
  geom: LineString | null;
  /** Mapped length from the API, when known. */
  lengthKm: number | null;
  /** True when score and level come from the saved one-week risk map. */
  fromRiskMap: boolean;
}

/** The header's one line of basic stats. */
export interface MountainStats {
  elevationM: number;
  /** Mean hillside slope across the mountain's box, in degrees. Null until scored. */
  meanSlopeDeg: number | null;
  /** Area of the mountain's bounding box, in km². Null for static mountains. */
  areaKm2: number | null;
}

export interface MountainView {
  slug: string;
  name: string;
  region: string;
  isLive: boolean;
  stats: MountainStats;
  /** The worst point on any mapped trail, 0 to 1, and its level. Null score until scored. */
  risk: { score: number | null; level: RiskLevel };
  /** Top five by risk when scored; otherwise every mapped route (up to five letters). */
  trails: TrailRisk[];
  /** Three to five short bullets. */
  preventative: string[];
  /** Where the scores came from. Null for static mountains and before the first saved map. */
  scoring: { scoredAt: string; method: string; trailsScored: number; shareAreaHigh: number } | null;
}

/** A request to fly the camera to a trail. `nonce` changes on every click, so a repeat click flies again. */
export interface CameraFocus {
  letter: TrailLetter;
  nonce: number;
}

// --- the agent pipeline ----------------------------------------------------------------

export const PIPELINE_AGENTS = ["terrain", "weather", "trails", "synthesizer", "alertWriter"] as const;
export type PipelineAgentId = (typeof PIPELINE_AGENTS)[number];

export const PIPELINE_LABELS: Record<PipelineAgentId, string> = {
  terrain: "Terrain",
  weather: "Weather",
  trails: "Trails",
  synthesizer: "Synthesizer",
  alertWriter: "Alerter",
};

export type PipelineStatus = "idle" | "running" | "done" | "error";

export interface PipelineAgentState {
  id: PipelineAgentId;
  status: PipelineStatus;
  /** One line under the card's name. */
  summary: string;
  /** The full reasoning trace, one step per entry, shown when the card is expanded. */
  trace: string[];
  startedAt: number | null;
  finishedAt: number | null;
}

/**
 * What kind of work a measure is, the way an incident is run. Shown as a label on each measure;
 * the panel groups measures by timing, not by category.
 */
export const MEASURE_CATEGORIES = ["closures", "evacuation", "rescue", "monitoring", "coordination", "public"] as const;
export type MeasureCategory = (typeof MEASURE_CATEGORIES)[number];

export const MEASURE_CATEGORY_LABELS: Record<MeasureCategory, string> = {
  closures: "Closures and access",
  evacuation: "Evacuation and sweeps",
  rescue: "Search and rescue readiness",
  monitoring: "Field monitoring",
  coordination: "Agency coordination",
  public: "Public notice",
};

/** When a measure has to happen. The panel clusters measures by these, soonest first. */
export const MEASURE_TIMINGS = ["now", "within-1h", "within-6h", "within-24h"] as const;
export type MeasureTiming = (typeof MEASURE_TIMINGS)[number];

export const MEASURE_TIMING_LABELS: Record<MeasureTiming, string> = {
  now: "Now",
  "within-1h": "Within 1 hour",
  "within-6h": "Within 6 hours",
  "within-24h": "Within 24 hours",
};

/** One thing to do. Public items are drafts; nothing is sent from the app. */
export interface ReactiveMeasure {
  category: MeasureCategory;
  title: string;
  detail: string;
  /** When it has to happen: the cluster it sits in. */
  timing: MeasureTiming;
  /** The trail it concerns, when it concerns one. */
  letter: TrailLetter | null;
}

export interface PipelineState {
  orchestrator: PipelineStatus;
  agents: Record<PipelineAgentId, PipelineAgentState>;
  /** Null until the Alerter finishes. */
  measures: ReactiveMeasure[] | null;
  /** The backend classifier result projected from the finished advisory. */
  model: {
    state: "HIGH_RISK" | "NOT_HIGH_RISK" | "UNCERTAIN" | null;
    probability: number | null;
    threshold: number | null;
    decisionEligible: boolean;
    reasonCodes: string[];
  } | null;
  error: string | null;
}
