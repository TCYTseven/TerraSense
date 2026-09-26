"use client";

import { useEffect, useRef } from "react";
import { CheckIcon, CircleIcon, MinusIcon, XIcon } from "@/components/icons";
import { formatClock } from "@/lib/format";
import type { AgentName, AgentTrace, Attempt, ProviderName, Run, ToolCall } from "@/lib/types";
import { AGENT_LABELS, type RowState } from "./agent-rows";

const PROVIDER_WORDS: Record<ProviderName, string> = { gemini: "Gemini", grok: "Grok" };

const NO_TOOLS: Partial<Record<AgentName, string>> = {
  synthesizer: "No tools. It reads the Terrain, Weather, and Trail reports, and the confidence the code computed from them.",
  writer: "No tools. It reads the final assessment, the ranger line the code filled in, and the bypass numbers.",
};

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function seconds(ms: number | null | undefined): string | null {
  return ms === null || ms === undefined ? null : `${(ms / 1000).toFixed(1)} s`;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-border px-5 py-4">
      <h3 className="text-xs text-muted-foreground">{title}</h3>
      <div className="mt-2 space-y-2 text-sm">{children}</div>
    </section>
  );
}

function Json({ value, label }: { value: unknown; label: string }) {
  return (
    <details className="group">
      <summary className="cursor-pointer text-xs text-primary underline decoration-1 underline-offset-3">{label}</summary>
      <pre className="mt-2 max-h-72 overflow-auto rounded-md bg-muted p-3 font-mono text-[11px] leading-4 text-foreground">
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  );
}

function argsText(args: Record<string, unknown>): string {
  return Object.entries(args)
    .map(([key, value]) => `${key}: ${JSON.stringify(value)}`)
    .join(", ");
}

function Tools({ tools }: { tools: ToolCall[] }) {
  return (
    <ul className="space-y-3">
      {tools.map((call, i) => (
        <li key={`${call.name}-${i}`}>
          <p className="break-words font-mono text-[0.92em]">
            {call.name}({argsText(call.args)})
            <span className="ml-2 text-xs text-muted-foreground">{call.ms} ms</span>
          </p>
          <div className="mt-1">
            <Json value={call.result} label="The facts it returned" />
          </div>
        </li>
      ))}
    </ul>
  );
}

function Attempts({ attempts }: { attempts: Attempt[] }) {
  return (
    <ol className="space-y-2">
      {attempts.map((attempt, i) => (
        <li key={i} className="flex gap-2">
          <span className="mt-0.5 shrink-0">
            {attempt.ok ? <CheckIcon className="size-4" /> : <XIcon className="size-4" />}
          </span>
          <span className="min-w-0">
            <span>
              {PROVIDER_WORDS[attempt.provider]} <span className="text-muted-foreground">({attempt.model})</span>
              {attempt.repair && <span className="text-muted-foreground">, asked again after a failed check</span>}
              <span className="ml-2 font-mono text-[0.92em] text-muted-foreground">{seconds(attempt.latency_ms)}</span>
            </span>
            {attempt.error && <span className="block break-words text-xs text-muted-foreground">{attempt.error}</span>}
          </span>
        </li>
      ))}
    </ol>
  );
}

function Verdict({ verdict }: { verdict: ProviderName | null }) {
  return (
    <span className="shrink-0 rounded-sm border border-border px-1.5 text-xs text-muted-foreground">
      {verdict ? `→ ${PROVIDER_WORDS[verdict]}` : "no change"}
    </span>
  );
}

function TraceView({ agent, trace, status, payload }: {
  agent: AgentName;
  trace: AgentTrace;
  status: RowState["status"];
  payload: Record<string, unknown>;
}) {
  const route = trace.route;
  const answered = [...trace.attempts].reverse().find((attempt) => attempt.ok);
  const usage = trace.usage;
  const tokens = usage
    ? [
        usage.input_tokens !== null && `${usage.input_tokens.toLocaleString("en-US")} in`,
        usage.output_tokens !== null && `${usage.output_tokens.toLocaleString("en-US")} out`,
        usage.reasoning_tokens !== null && `${usage.reasoning_tokens.toLocaleString("en-US")} thinking`,
      ].filter(Boolean)
    : [];
  return (
    <>
      <Section title="Model">
        <p className="text-base font-medium">{route.label}</p>
        <p className="text-xs text-muted-foreground">
          {capitalize(route.tier)} tier
          {answered && answered.model !== route.model && <> · answered by {answered.model}</>}
          {trace.latency_ms !== null && <> · <span className="font-mono text-[0.92em]">{seconds(trace.latency_ms)}</span></>}
          {tokens.length > 0 && <> · <span className="font-mono text-[0.92em]">{tokens.join(", ")}</span></>}
        </p>
        {status === "running" && (
          <p className="animate-work text-muted-foreground motion-reduce:animate-none">Waiting for {route.label}…</p>
        )}
      </Section>

      <Section title="Why this model">
        <p>{route.reason}</p>
        <ul className="space-y-2">
          {route.rules.map((rule, i) => (
            <li key={`${rule.rule}-${i}`} className="text-xs">
              <span className="flex items-baseline justify-between gap-3">
                <span className="text-foreground">{capitalize(rule.rule)}</span>
                <Verdict verdict={rule.verdict} />
              </span>
              <span className="block text-muted-foreground">{rule.detail}</span>
            </li>
          ))}
        </ul>
        <p className="text-xs text-muted-foreground">
          {route.fallback.length > 0
            ? `If ${PROVIDER_WORDS[route.provider]} fails, ${route.fallback.map((p) => PROVIDER_WORDS[p]).join(" then ")} takes the call.`
            : "No fallback provider is available for this call."}
        </p>
      </Section>

      <Section title="What it read">
        {trace.tools.length > 0 ? <Tools tools={trace.tools} /> : <p className="text-muted-foreground">{NO_TOOLS[agent] ?? "No tool calls yet."}</p>}
      </Section>

      {(trace.thoughts.length > 0 || trace.reasoning.length > 0) && (
        <Section title="How it reasoned">
          {trace.thoughts.length > 0 && (
            <div>
              <p className="text-xs text-muted-foreground">{PROVIDER_WORDS[route.provider]}&apos;s thinking summary</p>
              <blockquote className="mt-1 space-y-1 border-l-2 border-foreground/40 pl-3 text-muted-foreground">
                {trace.thoughts.map((thought, i) => (
                  <p key={i} className="whitespace-pre-line">{thought}</p>
                ))}
              </blockquote>
            </div>
          )}
          {trace.reasoning.length > 0 && (
            <div>
              <p className="text-xs text-muted-foreground">The steps it gave</p>
              <ol className="mt-1 list-decimal space-y-1 pl-5">
                {trace.reasoning.map((step, i) => (
                  <li key={i}>{step}</li>
                ))}
              </ol>
            </div>
          )}
        </Section>
      )}

      {trace.checks.length > 0 && (
        <Section title="What the code did">
          <ul className="list-disc space-y-1 pl-5">
            {trace.checks.map((check, i) => (
              <li key={i}>{check}</li>
            ))}
          </ul>
        </Section>
      )}

      {trace.attempts.length > 0 && (
        <Section title={trace.attempts.length === 1 ? "Call" : "Calls, in order"}>
          <Attempts attempts={trace.attempts} />
        </Section>
      )}

      {(trace.output || Object.keys(payload).length > 0) && (
        <Section title="Answer">
          {trace.output && <Json value={trace.output} label="What the model returned" />}
          {Object.keys(payload).length > 0 && <Json value={payload} label="What the pipeline passed on" />}
        </Section>
      )}
    </>
  );
}

function TabGlyph({ status }: { status: RowState["status"] }) {
  if (status === "done") return <CheckIcon className="size-3.5" />;
  if (status === "error") return <XIcon className="size-3.5" />;
  if (status === "skipped") return <MinusIcon className="size-3.5" />;
  if (status === "running") return <span aria-hidden className="grid size-3.5 place-items-center"><span className="size-1.5 rounded-full bg-current" /></span>;
  return <CircleIcon className="size-3.5" />;
}

/**
 * The reasoning side panel (user direction, Sep 25, 2026): for each agent, which model the router
 * picked and why, the facts the agent read, how the model reasoned, what the code changed, and
 * every call it took. It opens beside the ranger panel, over the map, and updates live.
 */
export default function ReasoningPanel({
  run,
  rows,
  agent,
  onAgent,
  onClose,
}: {
  run: Run | null;
  rows: RowState[];
  agent: AgentName;
  onAgent: (agent: AgentName) => void;
  onClose: () => void;
}) {
  const closeButton = useRef<HTMLButtonElement>(null);
  const row = rows.find((r) => r.agent === agent) ?? rows[0];
  const event = row.event;

  useEffect(() => {
    closeButton.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const runLine = !run
    ? "No run yet."
    : run.status === "running"
      ? `Running since ${formatClock(run.started_at)}.`
      : `${run.status === "done" ? "Finished" : "Failed"} at ${formatClock(run.finished_at ?? run.started_at)}.`;

  return (
    <section
      role="dialog"
      aria-modal="false"
      aria-labelledby="reasoning-title"
      className="fixed inset-0 z-30 flex flex-col bg-card md:absolute md:inset-y-0 md:left-auto md:right-0 md:w-[min(520px,100%)] md:border-l md:border-border"
    >
      <header className="flex items-start justify-between gap-4 px-5 pb-3 pt-5">
        <div>
          <h2 id="reasoning-title" className="text-base font-semibold">Reasoning</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            A router sends each agent to Gemini Flash or Grok. Pick an agent to see why, what it read, and how it
            reasoned. {runLine}
          </p>
        </div>
        <button
          ref={closeButton}
          type="button"
          onClick={onClose}
          aria-label="Close the reasoning panel"
          className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          <XIcon className="size-5" />
        </button>
      </header>

      <div role="tablist" aria-label="Agents" className="flex gap-1 overflow-x-auto px-5 pb-3">
        {rows.map((r) => (
          <button
            key={r.agent}
            type="button"
            role="tab"
            aria-selected={r.agent === agent}
            onClick={() => onAgent(r.agent)}
            className={`flex h-8 shrink-0 items-center gap-1.5 rounded-md border px-2.5 text-xs ${
              r.agent === agent ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:bg-accent"
            }`}
          >
            <TabGlyph status={r.status} />
            {AGENT_LABELS[r.agent]}
          </button>
        ))}
      </div>

      <div role="tabpanel" aria-label={AGENT_LABELS[agent]} className="min-h-0 flex-1 overflow-y-auto pb-6">
        {!run && (
          <p className="border-t border-border px-5 py-4 text-sm text-muted-foreground">
            Run Analyze now to see each agent&apos;s reasoning.
          </p>
        )}
        {run && !event && (
          <p className="border-t border-border px-5 py-4 text-sm text-muted-foreground">
            {row.status === "skipped"
              ? "The run stopped before it reached this agent."
              : "Waiting for the run to reach this agent."}
          </p>
        )}
        {event && event.status === "error" && (
          <p className="border-t border-border px-5 py-4 text-sm">
            <span className="block border-l-2 border-foreground/40 pl-2 text-xs">{row.line}</span>
          </p>
        )}
        {event?.trace && <TraceView agent={agent} trace={event.trace} status={row.status} payload={event.payload} />}
        {event && !event.trace && event.status !== "error" && (
          <p className="border-t border-border px-5 py-4 text-sm text-muted-foreground">This event has no trace.</p>
        )}
      </div>
    </section>
  );
}
