"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckIcon } from "@/components/icons";
import type { MountainView, PipelineState, ReactiveMeasure } from "@/lib/mountain-view";
import { buildResponsePlan, type PlanPriorityBlock, type ResponsePlan } from "@/lib/response-plan";
import type { Advisory } from "@/lib/types";

type Phase = "plan" | "submitting" | "confirmed";

const SUBMIT_MS = 900;

function PriorityBlock({ block }: { block: PlanPriorityBlock }) {
  const [group, verb] = block.title.split("·").map((s) => s.trim());
  return (
    <section className="flex gap-4 py-4">
      <span className="mt-1 w-[2px] shrink-0 rounded-full bg-foreground/55" aria-hidden />
      <div className="min-w-0 flex-1">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
          <span className="text-foreground">{group}</span>
          {verb ? ` — ${verb}` : ""}
        </h3>
        <ul className="mt-2.5 space-y-2">
          {block.actions.map((action) => (
            <li key={action.text} className="flex gap-2.5 text-[0.9375rem] leading-relaxed text-foreground/90">
              <CheckIcon className="mt-[0.3rem] size-3.5 shrink-0 text-foreground/70" strokeWidth={3} />
              <span>{action.text}</span>
            </li>
          ))}
          {block.actions.length === 0 && (
            <li className="text-[0.9375rem] text-muted-foreground">No extra actions — monitor conditions.</li>
          )}
        </ul>
      </div>
    </section>
  );
}

/**
 * Response plan: editorial layout — white accent rail, inline meta, ranked actions, no scroll.
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
  const plan: ResponsePlan = useMemo(
    () => buildResponsePlan(advisory, measures, pipeline.agents, hill.region),
    [advisory, measures, pipeline.agents, hill.region],
  );
  const [phase, setPhase] = useState<Phase>("plan");

  useEffect(() => {
    if (!open) {
      setPhase("plan");
    }
  }, [open]);

  useEffect(() => {
    if (phase !== "submitting") {
      return;
    }
    const timer = window.setTimeout(() => setPhase("confirmed"), SUBMIT_MS);
    return () => window.clearTimeout(timer);
  }, [phase]);

  const approve = useCallback(() => {
    setPhase("submitting");
  }, []);

  useEffect(() => {
    if (!open) {
      return;
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/65 p-0 backdrop-blur-md sm:items-center sm:p-8"
      role="dialog"
      aria-modal="true"
      aria-labelledby="response-plan-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          onClose();
        }
      }}
    >
      <div className="relative flex w-full max-w-xl flex-col overflow-hidden rounded-t-2xl border border-border bg-card sm:rounded-2xl">
        <span className="absolute inset-x-0 top-0 h-px bg-foreground/40" aria-hidden />

        <header className="shrink-0 px-7 pb-5 pt-7">
          <div className="flex items-baseline justify-between gap-4">
            <p className="truncate text-[11px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">
              {hill.name}
            </p>
            <button
              type="button"
              onClick={onClose}
              className="-mr-2 rounded-md px-2 py-1 text-lg leading-none text-muted-foreground transition-colors hover:text-foreground"
              aria-label="Close"
            >
              ×
            </button>
          </div>

          <h2 id="response-plan-title" className="mt-3 text-[1.75rem] font-semibold leading-tight tracking-tight">
            {plan.modeLabel}
          </h2>
          <p className="mt-1.5 text-[0.9375rem] leading-snug text-muted-foreground">{plan.heroLine}</p>

          <dl className="mt-5 flex flex-wrap items-baseline gap-x-6 gap-y-2 border-t border-border pt-4">
            {plan.stats.map((stat) => (
              <div key={stat.label} className="flex min-w-0 items-baseline gap-2">
                <dt className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                  {stat.label}
                </dt>
                <dd className="truncate text-[15px] font-semibold tabular-nums text-foreground">{stat.value}</dd>
              </div>
            ))}
          </dl>
        </header>

        <div className="px-7 pb-6">
          {phase === "plan" && (
            <>
              <div className="divide-y divide-border border-t border-border">
                {plan.priorities.map((block) => (
                  <PriorityBlock key={block.rank} block={block} />
                ))}
              </div>

              {plan.fieldTags.length > 0 && (
                <p className="mt-5 flex flex-wrap items-baseline gap-x-2 gap-y-1 text-[0.875rem] text-foreground/75">
                  <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                    Closures
                  </span>
                  {plan.fieldTags.join(" · ")}
                </p>
              )}

              {plan.analysisSeconds != null && (
                <p className="mt-6 text-[11px] text-muted-foreground/70">
                  Built from a {plan.analysisSeconds}s agent run · approve simulates outbound alerts
                </p>
              )}
            </>
          )}

          {phase === "submitting" && (
            <div aria-live="polite" className="border-t border-border py-10">
              <p className="text-center text-sm text-muted-foreground">Sending plan to server…</p>
              <div className="mx-auto mt-4 h-0.5 w-32 overflow-hidden rounded-full bg-muted">
                <div className="h-full w-full origin-left animate-[plan-submit_0.9s_ease-out_forwards] bg-foreground/50" />
              </div>
            </div>
          )}

          {phase === "confirmed" && (
            <div aria-live="polite" className="border-t border-border py-8">
              <div className="flex items-center gap-3 text-[0.9375rem] text-foreground">
                <CheckIcon className="size-5 shrink-0 text-foreground/80" strokeWidth={2.5} aria-hidden />
                <p className="font-medium">Plan confirmed and sent to server</p>
              </div>
            </div>
          )}
        </div>

        <footer className="flex shrink-0 gap-2 border-t border-border bg-background/30 px-7 py-4">
          {phase === "plan" ? (
            <>
              <button
                type="button"
                onClick={approve}
                className="flex-[1.4] rounded-lg bg-primary py-3 text-sm font-semibold text-primary-foreground transition-colors hover:brightness-110"
              >
                Approve plan
              </button>
              <button
                type="button"
                onClick={onRevise}
                className="flex-1 rounded-lg border border-border py-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              >
                Revise
              </button>
            </>
          ) : phase === "submitting" ? (
            <button type="button" disabled className="w-full rounded-lg bg-primary/50 py-3 text-sm font-semibold text-primary-foreground">
              Sending…
            </button>
          ) : (
            <button
              type="button"
              onClick={onClose}
              className="w-full rounded-lg bg-primary py-3 text-sm font-semibold text-primary-foreground"
            >
              Done
            </button>
          )}
        </footer>
      </div>
    </div>
  );
}
