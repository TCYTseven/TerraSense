"use client";

import { useState } from "react";
import { PIPELINE_LABELS, type PipelineAgentId, type PipelineState } from "@/lib/mountain-view";
import { PARALLEL_AGENTS, SEQUENTIAL_AGENTS } from "@/lib/pipeline/state";
import AgentCard from "./agent-card";
import StatusGlyph, { STATUS_WORDS } from "./status-glyph";

type Row = { kind: "label"; text: string } | { kind: "agent"; id: PipelineAgentId };

// The rail under the orchestrator: the three parallel agents fan out from it, then the two
// sequential agents follow.
const ROWS: Row[] = [
  { kind: "label", text: "In parallel" },
  ...PARALLEL_AGENTS.map((id): Row => ({ kind: "agent", id })),
  { kind: "label", text: "Then, in order" },
  ...SEQUENTIAL_AGENTS.map((id): Row => ({ kind: "agent", id })),
];

function list(names: string[]): string {
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

function orchestratorLine(state: PipelineState): React.ReactNode {
  const agents = Object.values(state.agents);
  if (state.orchestrator === "error") return state.error ?? "The run failed.";
  if (state.orchestrator === "done") {
    const starts = agents.map((a) => a.startedAt).filter((t): t is number => t !== null);
    const ends = agents.map((a) => a.finishedAt).filter((t): t is number => t !== null);
    if (starts.length === 0 || ends.length === 0) return "Finished.";
    const total = ((Math.max(...ends) - Math.min(...starts)) / 1000).toFixed(1);
    return (
      <>
        All five agents finished in <span className="font-mono">{total} s</span>. Your response plan is ready.
      </>
    );
  }
  if (state.orchestrator === "running") {
    const parallelRunning = PARALLEL_AGENTS.filter((id) => state.agents[id].status === "running").map(
      (id) => PIPELINE_LABELS[id],
    );
    const parallelDone = PARALLEL_AGENTS.filter((id) => state.agents[id].status === "done").map(
      (id) => PIPELINE_LABELS[id],
    );
    if (parallelRunning.length >= 2) {
      return `${list(parallelRunning)} running together.`;
    }
    if (parallelRunning.length === 1 && parallelDone.length > 0) {
      return `${parallelRunning[0]} still running; ${list(parallelDone)} finished.`;
    }
    const running = agents.filter((a) => a.status === "running").map((a) => PIPELINE_LABELS[a.id]);
    return running.length > 0 ? `${list(running)} running.` : "Dispatching agents…";
  }
  return "Press Analyze now to run the agents.";
}

function modelLine(state: PipelineState): string | null {
  const model = state.model;
  if (!model) return null;
  if (model.decisionEligible && model.state) {
    const probability = model.probability == null ? "n/a" : `${Math.round(model.probability * 100)}%`;
    const threshold = model.threshold == null ? "n/a" : `${Math.round(model.threshold * 100)}%`;
    return `Production classifier: ${model.state.replaceAll("_", " ")} at ${probability} (high-risk threshold ${threshold}).`;
  }
  const reasons = model.reasonCodes.length ? ` ${model.reasonCodes.join(", ")}.` : "";
  return `Production classifier: UNCERTAIN; legacy map is visualization-only.${reasons}`;
}

/**
 * The orchestrator and its five agents. Terrain, Weather, and Trails branch off the rail together,
 * then the Synthesizer and the Alerter. The cards are there before any run, idle and empty, and
 * fill in as the run streams. A card opens its reasoning trace beneath it, one at a time.
 * Reactive Measures follow once the orchestrator finishes.
 */
export default function AgentPipeline({ state }: { state: PipelineState }) {
  const [expanded, setExpanded] = useState<PipelineAgentId | null>(null);

  const failed = state.orchestrator === "error";

  return (
    <div>
      <div
        role="status"
        aria-live="polite"
        className="flex items-start gap-3 rounded-md border border-border bg-card px-3 py-2.5"
      >
        <span className="mt-0.5 shrink-0">
          <StatusGlyph status={state.orchestrator} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline justify-between gap-3">
            <span className="text-base font-medium">Orchestrator</span>
            <span className="shrink-0 text-sm text-muted-foreground">{STATUS_WORDS[state.orchestrator]}</span>
          </span>
          <span className="block text-sm text-muted-foreground">{orchestratorLine(state)}</span>
          {modelLine(state) && <span className="mt-1 block text-sm text-muted-foreground">{modelLine(state)}</span>}
        </span>
      </div>

      <ol aria-label="Agents" className="mt-0">
        {ROWS.map((row, index) => {
          const last = index === ROWS.length - 1;
          const rail = (
            <span
              aria-hidden
              className={`absolute left-5 top-0 w-px bg-border ${last ? "h-6" : "bottom-0"}`}
            />
          );
          if (row.kind === "label") {
            return (
              <li key={row.text} aria-hidden className="relative pb-1.5 pl-9 pt-2.5">
                {rail}
                <span className="text-sm text-muted-foreground">{row.text}</span>
              </li>
            );
          }
          const agent = state.agents[row.id];
          return (
            <li key={row.id} className="relative pb-2 pl-9">
              {rail}
              <span aria-hidden className="absolute left-5 top-6 h-px w-4 bg-border" />
              <AgentCard
                agent={agent}
                expanded={expanded === row.id}
                notReached={failed && agent.status === "idle"}
                onToggle={() => setExpanded((current) => (current === row.id ? null : row.id))}
              />
            </li>
          );
        })}
      </ol>

    </div>
  );
}
