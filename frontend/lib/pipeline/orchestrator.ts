/**
 * The mountain page's agent pipeline, framework-free. The orchestrator runs Terrain, Weather, and
 * Trails in parallel, then the Synthesizer, then the Alerter. Each agent runs through
 * an `AgentSource`; the scripted one below simulates them. A real adapter over the backend's run
 * stream (`lib/run-stream.ts`) can implement `AgentSource` without touching the components.
 */

import {
  PIPELINE_AGENTS,
  type MountainView,
  type PipelineAgentId,
  type PipelineAgentState,
  type PipelineState,
  type ReactiveMeasure,
} from "../mountain-view";
import { demoMeasures, scriptFor } from "./demo-traces";

/** Appends one step to the agent's trace while it runs. */
export type EmitStep = (step: string) => void;

/** Runs one agent to completion and resolves with its one-line summary. Throw to fail it. */
export type AgentRunner = (
  id: PipelineAgentId,
  hill: MountainView,
  emitStep: EmitStep,
  signal: AbortSignal,
) => Promise<string>;

export interface AgentSource {
  runAgent: AgentRunner;
  /** The measures, read once the Alerter finishes. */
  measures: (hill: MountainView) => ReactiveMeasure[] | Promise<ReactiveMeasure[]>;
}

/** The three agents that run together, then the two that run after, in order. */
export const PARALLEL_AGENTS: readonly PipelineAgentId[] = ["terrain", "weather", "trails"];
export const SEQUENTIAL_AGENTS: readonly PipelineAgentId[] = ["synthesizer", "alertWriter"];

function idleAgent(id: PipelineAgentId): PipelineAgentState {
  return { id, status: "idle", summary: "", trace: [], startedAt: null, finishedAt: null };
}

export function initialPipelineState(): PipelineState {
  return {
    orchestrator: "idle",
    agents: Object.fromEntries(PIPELINE_AGENTS.map((id) => [id, idleAgent(id)])) as PipelineState["agents"],
    measures: null,
    error: null,
  };
}

class AbortedError extends Error {
  constructor() {
    super("Aborted");
    this.name = "AbortError";
  }
}

/** Resolves after `ms`, or rejects as soon as the signal aborts. */
export function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new AbortedError());
      return;
    }
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(new AbortedError());
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

/**
 * The scripted source: each agent emits its steps evenly across its duration, then resolves with
 * its summary. `failAgent` makes one agent throw halfway, for checking the error path.
 */
export function createScriptedSource(options: { failAgent?: PipelineAgentId; speed?: number } = {}): AgentSource {
  const speed = options.speed ?? 1;
  return {
    async runAgent(id, hill, emitStep, signal) {
      const script = scriptFor(id, hill);
      const gap = script.durationMs / speed / (script.steps.length + 1);
      for (const [index, step] of script.steps.entries()) {
        await sleep(gap, signal);
        if (options.failAgent === id && index >= Math.floor(script.steps.length / 2)) {
          throw new Error(`${id} could not reach its data source`);
        }
        emitStep(step);
      }
      await sleep(gap, signal);
      return script.summary;
    },
    measures: demoMeasures,
  };
}

export const scriptedSource = createScriptedSource();

/**
 * Runs the pipeline and reports every change through `onUpdate`, always with a fresh state
 * object. Resolves when the run finishes or fails. After the signal aborts it stops quietly and
 * sends no more updates.
 */
export async function runPipeline(
  hill: MountainView,
  onUpdate: (state: PipelineState) => void,
  signal: AbortSignal,
  source: AgentSource = scriptedSource,
): Promise<void> {
  let state = initialPipelineState();
  const commit = (next: PipelineState) => {
    if (signal.aborted) return;
    state = next;
    onUpdate(state);
  };
  const patchAgent = (id: PipelineAgentId, patch: (agent: PipelineAgentState) => Partial<PipelineAgentState>) => {
    const agent = state.agents[id];
    commit({ ...state, agents: { ...state.agents, [id]: { ...agent, ...patch(agent) } } });
  };

  const runOne = async (id: PipelineAgentId): Promise<void> => {
    patchAgent(id, () => ({ status: "running", summary: "Running", startedAt: Date.now() }));
    try {
      const summary = await source.runAgent(
        id,
        hill,
        (step) => patchAgent(id, (agent) => ({ trace: [...agent.trace, step] })),
        signal,
      );
      patchAgent(id, () => ({ status: "done", summary, finishedAt: Date.now() }));
    } catch (error) {
      if (signal.aborted) throw error;
      const message = error instanceof Error ? error.message : String(error);
      patchAgent(id, () => ({ status: "error", summary: `Failed: ${message}`, finishedAt: Date.now() }));
      throw error;
    }
  };

  const fail = (error: unknown) => {
    if (signal.aborted) return;
    const message = error instanceof Error ? error.message : String(error);
    commit({ ...state, orchestrator: "error", error: message });
  };

  commit({ ...state, orchestrator: "running" });

  // Terrain, Weather, and Trails together. Each finishes on its own; a failure in one lets the
  // others finish, then stops the run before the Synthesizer.
  const gathered = await Promise.allSettled(PARALLEL_AGENTS.map(runOne));
  if (signal.aborted) return;
  const failed = gathered.find((result) => result.status === "rejected");
  if (failed) {
    fail(failed.reason);
    return;
  }

  try {
    for (const id of SEQUENTIAL_AGENTS) {
      await runOne(id);
    }
    const measures = await source.measures(hill);
    commit({ ...state, orchestrator: "done", measures });
  } catch (error) {
    fail(error);
  }
}
