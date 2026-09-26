import TrailBadge from "@/components/mountain/trail-badge";
import { LEVEL_TREATMENT, LevelWord } from "@/components/panel/level";
import {
  MEASURE_CATEGORY_LABELS,
  MEASURE_TIMING_LABELS,
  MEASURE_TIMINGS,
  type MeasureTiming,
  type ReactiveMeasure,
  type TrailRisk,
} from "@/lib/mountain-view";
import type { RiskLevel } from "@/lib/types";

function Measure({ measure, level }: { measure: ReactiveMeasure; level: RiskLevel | undefined }) {
  const draft = measure.category === "public";
  return (
    <li className="rounded-lg border border-border bg-background/50 px-4 py-3">
      <div className="flex items-start gap-3">
        {measure.letter && level ? (
          <span className="mt-0.5">
            <TrailBadge letter={measure.letter} level={level} />
            <span className="sr-only">Trail {measure.letter}</span>
          </span>
        ) : null}
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <p className="text-xs text-muted-foreground">{MEASURE_CATEGORY_LABELS[measure.category]}</p>
            {draft && (
              <span className="shrink-0 rounded-sm border border-border px-1.5 py-0.5 text-xs text-muted-foreground">
                Draft, not sent
              </span>
            )}
          </div>
          <p className="mt-0.5 text-base font-semibold leading-snug">{measure.title}</p>
          <p className="mt-1 text-sm leading-relaxed text-foreground/80">{measure.detail}</p>
        </div>
      </div>
    </li>
  );
}

function Cluster({
  timing,
  measures,
  levels,
}: {
  timing: MeasureTiming;
  measures: ReactiveMeasure[];
  levels: Map<string, RiskLevel>;
}) {
  if (measures.length === 0) return null;
  const headingId = `measures-${timing}`;
  // "Now" leads with weight, not color: color is reserved for risk.
  const now = timing === "now";
  return (
    <section aria-labelledby={headingId}>
      <h3
        id={headingId}
        className={`flex items-baseline gap-2 text-sm ${now ? "font-semibold text-foreground" : "font-medium text-muted-foreground"}`}
      >
        <span>{MEASURE_TIMING_LABELS[timing]}</span>
        <span className="font-mono text-[0.92em] font-normal text-muted-foreground">{measures.length}</span>
      </h3>
      <ul className="mt-2 space-y-2">
        {measures.map((measure, i) => (
          <Measure
            key={`${measure.title}-${i}`}
            measure={measure}
            level={measure.letter ? levels.get(measure.letter) : undefined}
          />
        ))}
      </ul>
    </section>
  );
}

/**
 * What to do after a run, clustered by when it has to happen (now, within 1 hour, 6 hours,
 * 24 hours), soonest first. Each measure is labeled with its kind of work. The section takes
 * the overall level's treatment, since these measures answer that level. Public notices are drafts.
 */
export default function ReactiveMeasures({
  measures,
  level,
  trails,
}: {
  measures: ReactiveMeasure[];
  level: RiskLevel;
  trails: TrailRisk[];
}) {
  const levels = new Map(trails.map((trail) => [trail.letter, trail.level]));
  const drafts = measures.filter((m) => m.category === "public").length;
  const actions = measures.length - drafts;
  const now = measures.filter((m) => m.timing === "now").length;
  return (
    <section
      id="reactive-measures"
      aria-labelledby="reactive-measures-title"
      className={`border-t border-border px-5 py-5 ${LEVEL_TREATMENT[level]}`}
    >
      <h2 id="reactive-measures-title" className="text-xl font-semibold tracking-[-0.01em]">
        Reactive Measures
      </h2>
      <p className="mt-1 flex flex-wrap items-center gap-x-2 text-sm text-muted-foreground">
        <span>Response to</span>
        <LevelWord level={level} className="font-semibold" />
        <span>risk ·</span>
        <span>
          <span className="font-mono text-foreground">{now}</span> now,{" "}
          <span className="font-mono text-foreground">{actions}</span> actions ·
        </span>
        <span>
          <span className="font-mono text-foreground">{drafts}</span> public drafts
        </span>
      </p>
      <div className="mt-4 space-y-5">
        {MEASURE_TIMINGS.map((timing) => (
          <Cluster key={timing} timing={timing} measures={measures.filter((m) => m.timing === timing)} levels={levels} />
        ))}
      </div>
    </section>
  );
}
