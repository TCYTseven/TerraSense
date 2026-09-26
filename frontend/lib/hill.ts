/**
 * The hill detail card's view model: what the mountain page renders, independent of where the
 * numbers come from. `lib/fixtures/hill-demo.ts` fills it from the mountain plus illustrative
 * values until the models land; a real adapter replaces it without touching the components.
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
  /** Hillside slope at the riskiest point, in degrees. */
  slopeDeg: number;
  /** The driver that contributes most, in plain words ("Steep slopes"). */
  primaryFactor: string;
  /** Where the marker sits and where "View" centers the camera. */
  center: Position;
  /** The camera zoom "View" flies to. */
  zoom: number;
  /** The trail line, when the mountain's trails include it. */
  geom: LineString | null;
}

/** The header's one line of basic stats. */
export interface HillStats {
  elevationM: number;
  /** Mean hillside slope across the mountain's box, in degrees. */
  meanSlopeDeg: number;
  /** Area of the mountain's bounding box, in km². */
  areaKm2: number;
}

export interface HillView {
  slug: string;
  name: string;
  region: string;
  isLive: boolean;
  stats: HillStats;
  /** The overall score, 0 to 1, and its level. */
  risk: { score: number; level: RiskLevel };
  /** Exactly the top five, riskiest first, lettered A to E. Empty for static mountains. */
  trails: TrailRisk[];
  /** Three to five short bullets. */
  preventative: string[];
  /** True while any number above is illustrative rather than model output. */
  isDemo: boolean;
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
  alertWriter: "Mass Alert Writer",
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

/** What the rangers or the public should do now. Public items are drafts; nothing is sent. */
export interface ReactiveMeasure {
  audience: "rangers" | "public";
  title: string;
  detail: string;
  /** The trail it concerns, when it concerns one. */
  letter: TrailLetter | null;
}

export interface PipelineState {
  orchestrator: PipelineStatus;
  agents: Record<PipelineAgentId, PipelineAgentState>;
  /** Null until the Mass Alert Writer finishes. */
  measures: ReactiveMeasure[] | null;
  error: string | null;
}
