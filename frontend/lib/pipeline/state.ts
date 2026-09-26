import {
  PIPELINE_AGENTS,
  type PipelineAgentId,
  type PipelineAgentState,
  type PipelineState,
} from "../mountain-view";

/** The backend's analyst fan-out, projected into the five UI cards. */
export const PARALLEL_AGENTS: readonly PipelineAgentId[] = ["terrain", "weather", "trails"];
export const SEQUENTIAL_AGENTS: readonly PipelineAgentId[] = ["synthesizer", "alertWriter"];

function idleAgent(id: PipelineAgentId): PipelineAgentState {
  return { id, status: "idle", summary: "", trace: [], startedAt: null, finishedAt: null };
}

/** Empty UI state before the live backend run starts or after an abort. */
export function initialPipelineState(): PipelineState {
  return {
    orchestrator: "idle",
    agents: Object.fromEntries(PIPELINE_AGENTS.map((id) => [id, idleAgent(id)])) as PipelineState["agents"],
    measures: null,
    model: null,
    error: null,
  };
}
