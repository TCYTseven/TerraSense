import { CheckIcon, CircleIcon, MinusIcon, XIcon } from "@/components/icons";
import { AGENT_NAMES, type AgentEvent, type AgentName, type Run } from "@/lib/types";

export const AGENT_LABELS: Record<AgentName, string> = {
  terrain: "Terrain",
  weather: "Weather",
  trail: "Trail",
  synthesizer: "Synthesizer",
  writer: "Alert Writer",
};

export type RowStatus = "waiting" | "running" | "done" | "error" | "skipped";

export interface RowState {
  agent: AgentName;
  status: RowStatus;
  line: string;
  /** The model the router picked, such as "Gemini 3.8 Flash". */
  model: string | null;
  event: AgentEvent | null;
}

/** Each agent's row from a run. No run: all waiting. A failed run skips the agents it never reached. */
export function rowStates(run: Run | null): RowState[] {
  return AGENT_NAMES.map((agent) => {
    const event = run?.agents[agent] ?? null;
    if (event) {
      const line =
        event.status === "error"
          ? event.summary.startsWith("Failed") ? event.summary : `Failed: ${event.summary}`
          : event.summary || (event.status === "running" ? "Running" : "");
      return { agent, status: event.status, line, model: event.trace?.route.label ?? null, event };
    }
    if (run && run.status === "error") {
      return { agent, status: "skipped", line: "Skipped", model: null, event: null };
    }
    return { agent, status: "waiting", line: "Waiting", model: null, event: null };
  });
}

function Glyph({ status }: { status: RowStatus }) {
  // Status never uses a risk color: green or red here would claim a risk level.
  switch (status) {
    case "running":
      return <span aria-hidden className="grid size-4 place-items-center"><span className="size-2 rounded-full bg-foreground" /></span>;
    case "done":
      return <CheckIcon className="size-4 text-foreground" />;
    case "error":
      return <XIcon className="size-4 text-foreground" />;
    case "skipped":
      return <MinusIcon className="size-4 text-muted-foreground" />;
    default:
      return <CircleIcon className="size-4 text-muted-foreground" />;
  }
}

const STATUS_WORDS: Record<RowStatus, string> = {
  waiting: "waiting",
  running: "running",
  done: "done",
  error: "failed",
  skipped: "skipped",
};

/**
 * The five agent rows, in pipeline order. Terrain and Weather run together, so two rows can run
 * at once. The running row pulses. A click opens the reasoning panel on that agent.
 */
export default function AgentRows({ rows, onOpen }: { rows: RowState[]; onOpen: (agent: AgentName) => void }) {
  return (
    <ol className="mt-2 space-y-0.5">
      {rows.map((row) => (
        <li key={row.agent}>
          <button
            type="button"
            onClick={() => onOpen(row.agent)}
            aria-label={`${AGENT_LABELS[row.agent]}, ${STATUS_WORDS[row.status]}. Show its reasoning.`}
            className={`flex w-full items-start gap-3 rounded-md px-2 py-2 text-left hover:bg-accent ${
              row.status === "running" ? "animate-work bg-foreground/4 motion-reduce:animate-none" : ""
            }`}
          >
            <span className="mt-0.5 shrink-0">
              <Glyph status={row.status} />
            </span>
            <span className="min-w-0 flex-1">
              <span className="flex items-baseline justify-between gap-3">
                <span className="text-sm">{AGENT_LABELS[row.agent]}</span>
                {row.model && <span className="shrink-0 text-xs text-muted-foreground">{row.model}</span>}
              </span>
              <span title={row.line} className="block truncate text-xs text-muted-foreground">
                {row.line}
              </span>
            </span>
          </button>
        </li>
      ))}
    </ol>
  );
}
