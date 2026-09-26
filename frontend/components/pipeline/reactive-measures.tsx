import TrailBadge from "@/components/hill/trail-badge";
import { LEVEL_TREATMENT, LevelWord } from "@/components/panel/level";
import {
  MEASURE_CATEGORIES,
  MEASURE_CATEGORY_LABELS,
  type MeasureCategory,
  type ReactiveMeasure,
  type TrailRisk,
} from "@/lib/hill";
import type { RiskLevel } from "@/lib/types";

/** "Now" is the loudest chip; later deadlines stay outlined. Neither uses a risk or accent color. */
function When({ when, category }: { when: string; category: MeasureCategory }) {
  if (category === "public") {
    return (
      <span className="shrink-0 rounded-sm border border-border px-1.5 py-0.5 text-xs text-muted-foreground">
        Draft, not sent
      </span>
    );
  }
  return (
    <span
      className={`shrink-0 rounded-sm px-1.5 py-0.5 text-xs font-semibold ${
        when === "Now" ? "bg-foreground text-background" : "border border-border text-foreground"
      }`}
    >
      {when}
    </span>
  );
}

function Group({
  category,
  measures,
  levels,
}: {
  category: MeasureCategory;
  measures: ReactiveMeasure[];
  levels: Map<string, RiskLevel>;
}) {
  if (measures.length === 0) return null;
  const headingId = `measures-${category}`;
  return (
    <section aria-labelledby={headingId}>
      <h4 id={headingId} className="flex items-baseline justify-between gap-3 text-sm font-medium text-muted-foreground">
        <span>{MEASURE_CATEGORY_LABELS[category]}</span>
        {category === "public" && <span className="text-xs font-normal">Nothing is sent from here</span>}
      </h4>
      <ul className="mt-2 space-y-2">
        {measures.map((measure, i) => {
          const level = measure.letter ? levels.get(measure.letter) : undefined;
          return (
            <li key={`${measure.title}-${i}`} className="rounded-lg border border-border bg-background/50 px-4 py-3">
              <div className="flex items-start gap-3">
                {measure.letter && level ? (
                  <span className="mt-0.5">
                    <TrailBadge letter={measure.letter} level={level} />
                    <span className="sr-only">Trail {measure.letter}</span>
                  </span>
                ) : null}
                <div className="min-w-0 flex-1">
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-base font-semibold leading-snug">{measure.title}</p>
                    <When when={measure.when} category={measure.category} />
                  </div>
                  <p className="mt-1 text-sm leading-relaxed text-foreground/80">{measure.detail}</p>
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/**
 * What to do now, grouped the way an incident is run. The section takes the overall level's
 * treatment, since these measures are the answer to that level. Public notices are drafts.
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
  const now = measures.filter((m) => m.when === "Now").length;
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
          <span className="font-mono text-foreground">{actions}</span> actions,{" "}
          <span className="font-mono text-foreground">{now}</span> now ·
        </span>
        <span>
          <span className="font-mono text-foreground">{drafts}</span> public drafts
        </span>
      </p>
      <div className="mt-4 space-y-5">
        {MEASURE_CATEGORIES.map((category) => (
          <Group
            key={category}
            category={category}
            measures={measures.filter((m) => m.category === category)}
            levels={levels}
          />
        ))}
      </div>
    </section>
  );
}
