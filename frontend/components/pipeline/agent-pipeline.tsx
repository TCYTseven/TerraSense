"use client";

import { useState } from "react";
import { PIPELINE_LABELS, type PipelineAgentId, type PipelineState } from "@/lib/hill";
import { PARALLEL_AGENTS, SEQUENTIAL_AGENTS } from "@/lib/pipeline/orchestrator";
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
        All five agents finished in <span className="font-mono">{total} s</span>. Reactive Measures are below.
      </>
    );
  }
  if (state.orchestrator === "running") {
    const running = agents.filter((a) => a.status === "running").map((a) => PIPELINE_LABELS[a.id]);
    return running.length > 0 ? `Waiting on ${list(running)}.` : "Dispatching agents…";
  }
  return "Idle.";
}

/**
 * The orchestrator and its five agents. Terrain, Weather, and Trails branch off the rail together,
 * then the Synthesizer and the Mass Alert Writer. A card opens its reasoning trace beneath it, one
 * at a time. Reactive Measures follow once the orchestrator finishes.
 */
export default function AgentPipeline({ state }: { state: PipelineState }) {
  const [expanded, setExpanded] = useState<PipelineAgentId | null>(null);

  if (state.orchestrator === "idle") {
    return <p className="text-base text-muted-foreground">Press Analyze now to run the agents.</p>;
  }

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
