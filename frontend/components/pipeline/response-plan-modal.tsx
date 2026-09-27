"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckIcon, TriangleAlertIcon } from "@/components/icons";
import { LEVEL_TEXT, LevelWord } from "@/components/panel/level";
import type { MountainView, PipelineState, ReactiveMeasure } from "@/lib/mountain-view";
import { buildResponsePlan, dispatchTasks, type PlanPriorityBlock, type ResponsePlan } from "@/lib/response-plan";
import type { Advisory } from "@/lib/types";

type Phase = "plan" | "dispatch" | "done";

function StatBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col items-center justify-center px-2 py-3">
      <span className="text-2xl font-semibold tabular-nums tracking-tight text-foreground">{value}</span>
      <span className="mt-1 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">{label}</span>
    </div>
  );
}

function PriorityColumn({ block }: { block: PlanPriorityBlock }) {
  const critical = block.emphasis === "critical";
  return (
    <article
      className={`flex min-h-[140px] flex-col rounded-2xl border p-4 ${
        critical ? "border-amber-500/35 bg-gradient-to-b from-amber-500/12 to-transparent" : "border-border/70 bg-muted/20"
      }`}
    >
      <div className="flex items-center gap-2">
        <span
          className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold ${
            critical ? "bg-amber-500 text-amber-950" : "bg-foreground/10 text-foreground"
          }`}
        >
          {block.rank}
        </span>
        <h3 className="text-sm font-semibold uppercase tracking-wide text-foreground">{block.title}</h3>
      </div>
      <ul className="mt-4 flex flex-1 flex-col justify-center gap-2.5">
        {block.actions.map((action) => (
          <li key={action.text} className="flex items-start gap-2 text-sm leading-snug text-foreground/90">
            <CheckIcon className="mt-0.5 size-4 shrink-0 text-primary" strokeWidth={2.5} />
            <span>{action.text}</span>
          </li>
        ))}
        {block.actions.length === 0 && (
          <li className="text-sm text-muted-foreground">No extra actions — monitor conditions.</li>
        )}
      </ul>
    </article>
  );
}

function severityGlow(severity: ResponsePlan["severity"]): string {
  switch (severity) {
    case "extreme":
      return "shadow-[0_0_80px_-20px] shadow-risk-extreme/40";
    case "high":
      return "shadow-[0_0_80px_-20px] shadow-risk-high/35";
    case "moderate":
      return "shadow-[0_0_60px_-24px] shadow-risk-moderate/30";
    default:
      return "";
  }
}

/**
 * Pitch-ready response plan: wide card, hero + stats, two priority columns, minimal copy.
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
      const done = window.setTimeout(() => setPhase("done"), 450);
      return () => window.clearTimeout(done);
    }
    const tick = window.setTimeout(() => setTaskIndex((i) => i + 1), 550);
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
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 p-0 backdrop-blur-md sm:items-center sm:p-8"
      role="dialog"
      aria-modal="true"
      aria-labelledby="response-plan-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          onClose();
        }
      }}
    >
      <div
        className={`relative flex max-h-[min(88dvh,640px)] w-full max-w-2xl flex-col overflow-hidden rounded-t-3xl border border-border/80 bg-card sm:rounded-3xl ${severityGlow(plan.severity)}`}
      >
        <header className="relative shrink-0 border-b border-border/60 px-6 pb-4 pt-6 sm:px-8">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">{hill.name}</p>
              <div className="mt-2 flex flex-wrap items-center gap-3">
                <TriangleAlertIcon className={`size-8 ${LEVEL_TEXT[plan.severity]}`} strokeWidth={1.75} />
                <h2 id="response-plan-title" className="text-2xl font-bold tracking-tight sm:text-[1.65rem]">
                  {plan.modeLabel}
                </h2>
              </div>
              <p className="mt-2 max-w-xl text-base font-medium text-foreground/85">{plan.heroLine}</p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <LevelWord level={plan.severity} className="text-sm font-semibold" />
              <button
                type="button"
                onClick={onClose}
                className="rounded-full p-2 text-muted-foreground hover:bg-muted"
                aria-label="Close"
              >
                ×
              </button>
            </div>
          </div>

          <div className="mt-5 grid grid-cols-3 divide-x divide-border/60 rounded-2xl border border-border/60 bg-background/40">
            {plan.stats.map((stat) => (
              <StatBlock key={stat.label} label={stat.label} value={stat.value} />
            ))}
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5 sm:px-8">
          {phase === "plan" && (
            <>
              <p className="mb-3 text-[11px] font-bold uppercase tracking-[0.18em] text-muted-foreground">
                Priority actions
              </p>
              <div className="grid gap-4 sm:grid-cols-2">
                {plan.priorities.map((block) => (
                  <PriorityColumn key={block.rank} block={block} />
                ))}
              </div>

              {plan.fieldTags.length > 0 && (
                <div className="mt-5 flex flex-wrap items-center gap-2">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Closures</span>
                  {plan.fieldTags.map((tag) => (
                    <span key={tag} className="rounded-full bg-foreground/8 px-3 py-1 text-xs font-medium text-foreground/80">
                      {tag}
                    </span>
                  ))}
                </div>
              )}

              {plan.analysisSeconds != null && (
                <p className="mt-4 text-center text-[11px] text-muted-foreground">
                  Built from a {plan.analysisSeconds}s agent run · approve simulates outbound alerts
                </p>
              )}
            </>
          )}

          {(phase === "dispatch" || phase === "done") && (
            <div aria-live="polite">
              <p className="text-lg font-semibold">{phase === "done" ? "Dispatched" : "Dispatching…"}</p>
              <div className="mt-4 flex flex-wrap gap-2">
                {tasks.map((task, index) => {
                  const done = index < taskIndex;
                  const active = index === taskIndex && phase === "dispatch";
                  return (
                    <span
                      key={task}
                      className={`rounded-full px-4 py-2 text-sm font-medium transition-all ${
                        done
                          ? "bg-primary text-primary-foreground"
                          : active
                            ? "bg-primary/20 text-foreground ring-2 ring-primary/50 animate-pulse"
                            : "bg-muted text-muted-foreground"
                      }`}
                    >
                      {done ? "✓ " : ""}
                      {task}
                    </span>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        <footer className="shrink-0 flex gap-3 border-t border-border/60 px-6 py-5 sm:px-8">
          {phase === "plan" ? (
            <>
              <button
                type="button"
                onClick={approve}
                className="flex-[1.2] rounded-2xl bg-primary py-3.5 text-sm font-bold uppercase tracking-wide text-primary-foreground shadow-lg shadow-primary/20 hover:brightness-105"
              >
                Approve plan
              </button>
              <button
                type="button"
                onClick={onRevise}
                className="flex-1 rounded-2xl border border-border py-3.5 text-sm font-semibold text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                Revise
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={onClose}
              className="w-full rounded-2xl bg-primary py-3.5 text-sm font-bold text-primary-foreground"
            >
              Done
            </button>
          )}
        </footer>
      </div>
    </div>
  );
}
