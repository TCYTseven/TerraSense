// The surface synced to Claude Design, all from the app's own source.
// Tokens come from .design-sync/tokens.css (design addendum + spec), not from this entry.
//
// In: the risk vocabulary (RiskBadge, LevelWord, NeedsReviewTag, TrailBadge) and the hill
// detail card's presentational pieces (context/design-addendum.md, Panel): the overall risk
// block, the top-5 trail list, preventative measures, the agent pipeline and its cards, the
// Reactive Measures section, and Analyze now. Plus the scripted pipeline hook, so a design can
// play a run.
// Out: HillHeader (next/link needs the Next router), the map (MapLibre, WebGL), the globe
// (three.js), the hiker card and hazard block (not rendered on the page), and THEME from
// lib/theme.ts (for WebGL; it predates the role names). See .design-sync/NOTES.md.

// Risk vocabulary.
export { default as RiskBadge } from "@/components/risk-badge";
export { LevelWord, NeedsReviewTag } from "@/components/panel/level";
export { default as TrailBadge } from "@/components/hill/trail-badge";

// Hill detail card, right panel, top to bottom.
export { default as OverallRisk } from "@/components/hill/overall-risk";
export { default as TrailList } from "@/components/hill/trail-list";
export { default as PreventativeMeasures } from "@/components/hill/preventative-measures";
export { default as AgentPipeline } from "@/components/pipeline/agent-pipeline";
export { default as AgentCard } from "@/components/pipeline/agent-card";
export { default as StatusGlyph } from "@/components/pipeline/status-glyph";
export { default as ReactiveMeasures } from "@/components/pipeline/reactive-measures";
export { default as AnalyzeButton } from "@/components/pipeline/analyze-button";

// Data helpers and the scripted run.
export { RISK_LEVELS } from "@/lib/types";
export type { RiskLevel } from "@/lib/types";
export { riskLabel, formatScore } from "@/lib/format";
export { RISK_COLORS } from "@/lib/theme";
export { levelForScore } from "@/lib/fixtures/hill-demo";
export {
  TRAIL_LETTERS,
  PIPELINE_AGENTS,
  PIPELINE_LABELS,
  MEASURE_CATEGORIES,
  MEASURE_CATEGORY_LABELS,
} from "@/lib/hill";
export type {
  TrailLetter,
  TrailRisk,
  HillStats,
  HillView,
  PipelineAgentId,
  PipelineStatus,
  PipelineAgentState,
  PipelineState,
  MeasureCategory,
  ReactiveMeasure,
} from "@/lib/hill";
export { usePipeline } from "@/lib/pipeline/use-pipeline";
export type { PipelineControls } from "@/lib/pipeline/use-pipeline";
export { initialPipelineState } from "@/lib/pipeline/orchestrator";
