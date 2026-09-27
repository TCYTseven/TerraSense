"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { LEVEL_TREATMENT, LevelWord } from "@/components/panel/level";
import type { MountainView, PipelineState, ReactiveMeasure } from "@/lib/mountain-view";
import { buildResponsePlan, dispatchTasks, type ResponsePlan } from "@/lib/response-plan";
import type { Advisory } from "@/lib/types";

type Phase = "plan" | "dispatch" | "done";

function AgentChip({ agent, fact }: { agent: string; fact: string }) {
  return (
    <div className="rounded-md border border-primary/25 bg-primary/5 px-2 py-1.5">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-primary">{agent}</p>
      <p className="mt-0.5 text-xs leading-snug text-foreground/90 line-clamp-2">{fact}</p>
    </div>
  );
}

function PriorityCard({ block }: { block: ResponsePlan["priorities"][number] }) {
  const critical = block.emphasis === "critical";
  return (
    <article
      className={`rounded-lg border px-4 py-3 ${
        critical ? "border-amber-500/50 bg-amber-500/10" : "border-border bg-background/60"
      }`}
    >
      <div className="flex items-start gap-3">
        <span
          className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full font-mono text-sm font-bold ${
            critical ? "bg-amber-500 text-amber-950" : "bg-muted text-foreground"
          }`}
        >
          {block.rank}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-base font-semibold leading-snug tracking-tight">{block.title}</h3>
          {block.chips.length > 0 && (
            <div className="mt-2 grid gap-1.5 sm:grid-cols-2">
              {block.chips.map((chip) => (
                <AgentChip key={`${chip.agent}-${chip.fact.slice(0, 24)}`} agent={chip.agent} fact={chip.fact} />
              ))}
            </div>
          )}
          <ul className="mt-2.5 list-disc space-y-1.5 pl-4 text-sm leading-snug text-foreground/90 marker:text-primary">
            {block.bullets.map((bullet) => (
              <li key={bullet.slice(0, 48)}>{bullet}</li>
            ))}
          </ul>
        </div>
      </div>
    </article>
  );
}

/**
 * Full-screen plan after Analyze finishes: priority blocks, agent-backed bullets, approve / revise.
 */
export default function ResponsePlanModal({
  open,
  hill,
  advisory,
  measures,
  pipeline,
  onClose,
  onRevise,
}: {
  open: boolean;
  hill: MountainView;
  advisory: Advisory;
  measures: ReactiveMeasure[];
  pipeline: PipelineState;
  onClose: () => void;
  onRevise: () => void;
}) {
  const plan = useMemo(
    () => buildResponsePlan(advisory, measures, pipeline.agents, hill.region),
    [advisory, measures, pipeline.agents, hill.region],
  );
  const [phase, setPhase] = useState<Phase>("plan");
  const [taskIndex, setTaskIndex] = useState(0);
  const tasks = useMemo(() => dispatchTasks(plan, advisory), [plan, advisory]);

  useEffect(() => {
    if (!open) {
      setPhase("plan");
      setTaskIndex(0);
    }
  }, [open]);

  useEffect(() => {
    if (phase !== "dispatch") {
      return;
    }
    if (taskIndex >= tasks.length) {
      const done = window.setTimeout(() => setPhase("done"), 400);
      return () => window.clearTimeout(done);
    }
    const tick = window.setTimeout(() => setTaskIndex((i) => i + 1), 520);
    return () => window.clearTimeout(tick);
  }, [phase, taskIndex, tasks.length]);

  const approve = useCallback(() => {
    setPhase("dispatch");
    setTaskIndex(0);
  }, []);

  if (!open) {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-background/70 p-0 backdrop-blur-sm sm:items-center sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="response-plan-title"
    >
      <div
        className={`flex max-h-[min(92dvh,720px)] w-full max-w-lg flex-col overflow-hidden rounded-t-xl border border-border bg-card shadow-2xl sm:rounded-xl ${LEVEL_TREATMENT[plan.severity]}`}
      >
        <header className="shrink-0 border-b border-border bg-gradient-to-br from-primary/10 via-card to-card px-5 py-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                Response plan · {hill.name}
              </p>
              <h2 id="response-plan-title" className="mt-1 text-xl font-semibold tracking-tight">
                {plan.serious ? "Elevated response" : "Watchful response"}
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">{hill.region}</p>
            </div>
            <LevelWord level={plan.severity} className="shrink-0 text-sm font-semibold" />
          </div>
          <p className="mt-3 text-sm leading-snug text-foreground/90">{plan.headline}</p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {plan.agentStrip.map((chip) => (
              <span
                key={`${chip.agent}-${chip.fact.slice(0, 20)}`}
                className="rounded-full border border-border bg-background/80 px-2 py-0.5 text-[10px] text-muted-foreground"
              >
                {chip.agent}
              </span>
            ))}
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {phase === "plan" && (
            <div className="space-y-4">
              {plan.priorities.map((block) => (
                <PriorityCard key={block.rank} block={block} />
              ))}
              {plan.fieldBullets.length > 0 && (
                <section>
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Field actions</h3>
                  <ul className="mt-2 list-disc space-y-1 pl-4 text-sm text-foreground/85">
                    {plan.fieldBullets.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </section>
              )}
              {plan.publicDraft && (
                <section className="rounded-lg border border-dashed border-border bg-muted/30 px-3 py-2.5">
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Public draft</p>
                  <p className="mt-1 text-sm font-semibold">{plan.publicDraft.title}</p>
                  <p className="mt-0.5 text-xs text-muted-foreground line-clamp-2">{plan.publicDraft.line}</p>
                </section>
              )}
            </div>
          )}

          {(phase === "dispatch" || phase === "done") && (
            <div className="space-y-3" aria-live="polite">
              <p className="text-sm font-medium text-foreground">
                {phase === "done" ? "Plan dispatched (simulated)" : "Dispatching…"}
              </p>
              <ul className="space-y-2">
                {tasks.map((task, index) => {
                  const active = index < taskIndex;
                  const current = index === taskIndex && phase === "dispatch";
                  return (
                    <li
                      key={task}
                      className={`flex items-center gap-2 rounded-md border px-3 py-2 text-sm ${
                        active ? "border-primary/40 bg-primary/10 text-foreground" : "border-border text-muted-foreground"
                      } ${current ? "animate-pulse" : ""}`}
                    >
                      <span className="font-mono text-xs">{active ? "✓" : current ? "…" : "·"}</span>
                      {task}
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </div>

        <footer className="shrink-0 flex flex-col gap-2 border-t border-border bg-card px-5 py-4 sm:flex-row">
          {phase === "plan" ? (
            <>
              <button
                type="button"
                onClick={approve}
                className="flex-1 rounded-md bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground hover:opacity-95"
              >
                Approve plan
              </button>
              <button
                type="button"
                onClick={onRevise}
                className="flex-1 rounded-md border border-border px-4 py-2.5 text-sm font-semibold text-foreground hover:bg-muted"
              >
                Reject and revise
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={onClose}
              className="w-full rounded-md bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground"
            >
              Close
            </button>
          )}
        </footer>
      </div>
    </div>
  );
}
