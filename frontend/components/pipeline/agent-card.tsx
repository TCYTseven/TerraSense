import { ChevronRightIcon } from "@/components/icons";
import { PIPELINE_LABELS, type PipelineAgentState } from "@/lib/hill";
import StatusGlyph, { STATUS_WORDS } from "./status-glyph";

function seconds(agent: PipelineAgentState): string | null {
  if (agent.startedAt === null || agent.finishedAt === null) return null;
  return `${((agent.finishedAt - agent.startedAt) / 1000).toFixed(1)} s`;
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
        <div id={traceId} className="border-t border-border px-4 py-3">
          {agent.trace.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {agent.status === "idle"
                ? notReached
                  ? "No reasoning: the run stopped before this agent."
                  : "No reasoning yet. It appears here once the agent runs."
                : "Starting…"}
            </p>
          ) : (
            <ol className="space-y-2 text-sm leading-relaxed">
              {agent.trace.map((step, i) => (
                <li key={i} className="flex gap-2">
                  <span className="w-5 shrink-0 text-right font-mono text-muted-foreground">{i + 1}</span>
                  <span className="min-w-0 break-words">{step}</span>
                </li>
              ))}
            </ol>
          )}
          {running && (
            <p className="mt-2 flex items-center gap-2 pl-7 text-sm text-muted-foreground">
              <span className="animate-work motion-reduce:animate-none">Thinking…</span>
            </p>
          )}
          {agent.status === "error" && (
            <p className="mt-2 border-l-2 border-foreground/40 pl-2 text-sm">{agent.summary}</p>
          )}
        </div>
      )}
    </div>
  );
}
