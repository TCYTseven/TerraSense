"use client";

import { useState } from "react";
import Link from "next/link";
import RiskBadge from "@/components/risk-badge";
import { getHistoryRun } from "@/lib/api";
import { formatUtc } from "@/lib/format";
import type { RunRecord, RunRecordDetail } from "@/lib/types";

/** The hazard tag's chip color. "unknown" is a run that failed before the terrain agent ruled. */
const CLASS_STYLE: Record<string, string> = {
  landslide: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  debris_flow: "border-orange-500/40 bg-orange-500/10 text-orange-300",
  avalanche: "border-sky-400/40 bg-sky-400/10 text-sky-300",
  unknown: "border-border bg-muted/40 text-muted-foreground",
};

const CLASS_LABEL: Record<string, string> = {
  landslide: "Landslide",
  debris_flow: "Debris flow",
  avalanche: "Avalanche",
  unknown: "Untagged",
};

function Chip({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs ${className}`}>
      {children}
    </span>
  );
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 break-words font-mono text-sm">{value ?? "—"}</dd>
    </div>
  );
}

/** A collapsed JSON payload. The log keeps everything, so the page never has to guess. */
function Json({ title, value }: { title: string; value: unknown }) {
  if (value == null) {
    return null;
  }
  return (
    <details className="rounded-lg border border-border bg-background/40">
      <summary className="cursor-pointer px-3 py-2 text-sm font-medium">{title}</summary>
      <pre className="max-h-96 overflow-auto border-t border-border px-3 py-2 font-mono text-xs leading-relaxed text-muted-foreground">
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  );
}

/**
 * One logged run. Collapsed it is the summary line; expanded it fetches the full record and
 * shows both sides of the run: what each agent said and what the ML model scored.
 */
export default function HistoryRow({ record }: { record: RunRecord }) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<RunRecordDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next && !detail) {
      try {
        setDetail(await getHistoryRun(record.run_id));
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Could not load this run.");
      }
    }
  }

  const failed = record.status === "error";
  const agents = Object.entries(detail?.agent_outputs ?? {});

  return (
    <li className="rounded-xl border border-border bg-card">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        className="flex w-full flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 text-left hover:bg-muted/40"
      >
        <span aria-hidden className="w-3 shrink-0 font-mono text-muted-foreground">
          {open ? "−" : "+"}
        </span>
        <span className="min-w-40 flex-1 font-medium">
          {record.mountain_name ?? record.mountain_slug}
        </span>
        <Chip className={CLASS_STYLE[record.hazard_class] ?? CLASS_STYLE.unknown}>
          {CLASS_LABEL[record.hazard_class] ?? record.hazard_class}
        </Chip>
        {record.snow_driven ? (
          <Chip className="border-sky-400/40 bg-sky-400/10 text-sky-300">Snow-driven</Chip>
        ) : null}
        <span className="min-w-28 text-sm">
          {record.severity ? <RiskBadge level={record.severity} /> : <span className="text-muted-foreground">No call</span>}
        </span>
        <Chip
          className={failed ? "border-destructive/40 bg-destructive/10 text-destructive" : "border-border bg-muted/40 text-muted-foreground"}
        >
          {failed ? `Failed${record.failed_agent ? ` at ${record.failed_agent}` : ""}` : record.status}
        </Chip>
        <span className="font-mono text-xs text-muted-foreground">
          {formatUtc(record.started_at)}
          {record.elapsed_s != null ? ` · ${record.elapsed_s.toFixed(1)}s` : ""}
        </span>
      </button>

      {open ? (
        <div className="space-y-4 border-t border-border px-4 py-4">
          {error ? <p className="text-sm text-destructive">{error}</p> : null}
          {!detail && !error ? <p className="text-sm text-muted-foreground">Loading the full record…</p> : null}

          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
            <Field label="Run id" value={<span className="text-xs">{record.run_id}</span>} />
            <Field label="Hazard type" value={record.hazard_type ?? "none"} />
            <Field label="Action" value={record.recommended_action} />
            <Field label="Posture" value={record.posture ? `${record.posture} · ${record.priority}` : null} />
            <Field label="Confidence" value={record.confidence != null ? record.confidence.toFixed(2) : null} />
            <Field label="Needs review" value={record.needs_review == null ? null : String(record.needs_review)} />
            <Field label="Finished" value={record.finished_at ? formatUtc(record.finished_at) : null} />
            <Field
              label="Mountain"
              value={
                <Link className="underline underline-offset-4" href={`/mountains/${record.mountain_slug}`}>
                  {record.mountain_slug}
                </Link>
              }
            />
          </dl>

          {record.headline || record.summary ? (
            <div className="rounded-lg border border-border bg-background/40 px-3 py-2">
              {record.headline ? <p className="font-medium">{record.headline}</p> : null}
              {record.summary ? <p className="mt-1 text-sm text-muted-foreground">{record.summary}</p> : null}
            </div>
          ) : null}

          {record.error ? (
            <p className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 font-mono text-xs text-destructive">
              {record.error}
            </p>
          ) : null}

          {/* The ML model's side of the run. */}
          <section>
            <h3 className="text-sm font-semibold">Model output</h3>
            <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
              <Field
                label="Method"
                value={`${record.model_method ?? "—"}${record.model_is_stand_in ? " (stand-in)" : ""}`}
              />
              <Field label="Map max" value={record.model_max_probability?.toFixed(3)} />
              <Field label="Map mean" value={detail?.model_mean_probability?.toFixed(3)} />
              <Field
                label="Share at high"
                value={record.model_share_at_high != null ? `${(record.model_share_at_high * 100).toFixed(0)}%` : null}
              />
            </dl>
            {detail?.model_note ? (
              <p className="mt-2 text-sm text-muted-foreground">{detail.model_note}</p>
            ) : null}
          </section>

          {/* The LLM side: who answered each agent, how fast, and what it cost. */}
          <section>
            <h3 className="text-sm font-semibold">
              Agent output{" "}
              <span className="font-normal text-muted-foreground">
                {record.llm_usage.calls ?? record.llm_calls.length} model calls ·{" "}
                {(record.llm_usage.input_tokens ?? 0) + (record.llm_usage.output_tokens ?? 0)} tokens
              </span>
            </h3>
            <div className="mt-2 overflow-x-auto">
              <table className="w-full min-w-[40rem] text-left text-sm">
                <thead className="text-xs uppercase tracking-wide text-muted-foreground">
                  <tr>
                    <th className="py-1 pr-4 font-normal">Agent</th>
                    <th className="py-1 pr-4 font-normal">Severity</th>
                    <th className="py-1 pr-4 font-normal">Confidence</th>
                    <th className="py-1 pr-4 font-normal">Provider</th>
                    <th className="py-1 pr-4 font-normal">Model</th>
                    <th className="py-1 pr-4 font-normal">Latency</th>
                  </tr>
                </thead>
                <tbody className="font-mono">
                  {record.llm_calls.map((call) => {
                    const verdict = record.agent_verdicts[call.agent];
                    return (
                      <tr key={call.agent} className="border-t border-border/60">
                        <td className="py-1 pr-4">{call.agent}</td>
                        <td className="py-1 pr-4">{verdict?.severity ?? "—"}</td>
                        <td className="py-1 pr-4">{verdict?.confidence?.toFixed(2) ?? "—"}</td>
                        <td className="py-1 pr-4">{call.provider ?? "—"}</td>
                        <td className="py-1 pr-4">{call.model ?? "—"}</td>
                        <td className="py-1 pr-4">{call.latency_ms != null ? `${call.latency_ms} ms` : "—"}</td>
                      </tr>
                    );
                  })}
                  {record.llm_calls.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="py-2 text-muted-foreground">
                        This run failed before any agent reached a model.
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </section>

          {/* Everything the log kept, verbatim. */}
          {detail ? (
            <section className="space-y-2">
              <h3 className="text-sm font-semibold">Raw record</h3>
              {agents.map(([name, event]) => (
                <Json key={name} title={`Agent: ${name}`} value={event} />
              ))}
              <Json title="Advisory" value={detail.advisory} />
              <Json title="Conditions" value={detail.conditions} />
              <Json title="Rain" value={detail.rain} />
              <Json title="Model output" value={detail.model_output} />
              <Json title="Whole run" value={detail.run} />
            </section>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}
