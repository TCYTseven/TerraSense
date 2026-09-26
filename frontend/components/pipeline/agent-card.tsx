import { ChevronRightIcon } from "@/components/icons";
import { PIPELINE_LABELS, type PipelineAgentState } from "@/lib/hill";
import StatusGlyph, { STATUS_WORDS } from "./status-glyph";

function seconds(agent: PipelineAgentState): string | null {
  if (agent.startedAt === null || agent.finishedAt === null) return null;
  return `${((agent.finishedAt - agent.startedAt) / 1000).toFixed(1)} s`;
}

/** Tool calls, model attempts, and route lines belong in the terminal. The rest is the write-up. */
function isLogLine(step: string): boolean {
  const text = step.replace(/^(?:Terrain|Weather|Trails|History|Routes|Synthesizer|Alert writer): /, "");
  return text.startsWith("Tool ") || text.includes(" · ") || /\b(?:answered|failed:)/.test(text);
}

function splitTrace(trace: string[]): { log: string[]; prose: string[] } {
  const log: string[] = [];
  const prose: string[] = [];
  for (const step of trace) {
    (isLogLine(step) ? log : prose).push(step);
  }
  return { log, prose };
}

/**
 * The opened trace: one terminal for the calls, then the write-up as continuous lines.
 */
function AgentTrace({ trace, time }: { trace: string[]; time: string | null }) {
  const { log, prose } = splitTrace(trace);
  return (
    <div className="space-y-3">
      {log.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-border bg-background">
          <div className="flex items-center justify-between border-b border-border px-3 py-1.5 text-xs text-muted-foreground">
            <span className="font-mono">agent</span>
            {time && <span className="font-mono">worked {time}</span>}
          </div>
          <div className="px-3 py-2 font-mono text-[13px] leading-5 text-foreground/90">
            {log.map((line, i) => (
              <p key={i} className="whitespace-pre-wrap break-words">
                {line}
              </p>
            ))}
          </div>
        </div>
      )}
      {prose.length > 0 && (
        <div className="px-0.5 text-sm leading-6 text-foreground/90">
          {prose.map((line, i) => (
            <p key={i} className="break-words">
              {line}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * One agent: name, status, and summary. A click opens its reasoning trace directly beneath it.
 * `notReached` marks an idle agent the failed run never got to.
 */
export default function AgentCard({
  agent,
  expanded,
  notReached,
  onToggle,
}: {
  agent: PipelineAgentState;
  expanded: boolean;
  notReached: boolean;
  onToggle: () => void;
}) {
  const label = PIPELINE_LABELS[agent.id];
  const traceId = `pipeline-trace-${agent.id}`;
  const running = agent.status === "running";
  const statusWord = notReached ? "not reached" : STATUS_WORDS[agent.status];
  const line = agent.summary || (notReached ? "The run stopped before this agent." : "Waiting");
  const time = seconds(agent);

  return (
    <div className="rounded-md border border-border bg-card">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        aria-controls={traceId}
        aria-label={`${label}, ${statusWord}. ${expanded ? "Hide" : "Show"} its reasoning.`}
        className={`flex w-full items-start gap-3 rounded-md px-3 py-2.5 text-left hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring ${
          running ? "animate-work bg-foreground/4 motion-reduce:animate-none" : ""
        }`}
      >
        <span className="mt-0.5 shrink-0">
          <StatusGlyph status={agent.status} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline justify-between gap-3">
            <span className="text-base">{label}</span>
            <span className="shrink-0 text-sm text-muted-foreground">
              {time && <span className="mr-1.5 font-mono">{time}</span>}
              {statusWord}
            </span>
          </span>
          <span title={line} className="block truncate text-sm text-muted-foreground">
            {line}
          </span>
        </span>
        <ChevronRightIcon
          className={`mt-0.5 size-4 shrink-0 text-muted-foreground ${expanded ? "rotate-90" : ""}`}
        />
      </button>
      {expanded && (
        <div id={traceId} className="border-t border-border px-3 py-3">
          {agent.trace.length === 0 ? (
            <p className="px-1 text-sm text-muted-foreground">
              {agent.status === "idle"
                ? notReached
                  ? "No reasoning: the run stopped before this agent."
                  : "No reasoning yet. It appears here once the agent runs."
                : "Starting…"}
            </p>
          ) : (
            <AgentTrace trace={agent.trace} time={time} />
          )}
          {running && (
            <p className="mt-2 px-1 text-sm text-muted-foreground">
              <span className="animate-work motion-reduce:animate-none">Thinking…</span>
            </p>
          )}
        </div>
      )}
    </div>
  );
}
