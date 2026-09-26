import type { ReactiveMeasure } from "@/lib/hill";

function Group({ title, note, measures }: { title: string; note?: string; measures: ReactiveMeasure[] }) {
  if (measures.length === 0) return null;
  return (
    <div>
      <h4 className="flex items-baseline justify-between gap-3 text-xs text-muted-foreground">
        <span>{title}</span>
        {note && <span>{note}</span>}
      </h4>
      <ul className="mt-1.5 space-y-1.5">
        {measures.map((measure, i) => (
          <li key={`${measure.title}-${i}`} className="flex gap-2.5 rounded-md border border-border bg-card px-2.5 py-2">
            {measure.letter ? (
              <span
                aria-label={`Trail ${measure.letter}`}
                className="grid size-5 shrink-0 place-items-center rounded-sm border border-border font-mono text-xs"
              >
                {measure.letter}
              </span>
            ) : (
              <span aria-hidden className="size-5 shrink-0" />
            )}
            <span className="min-w-0">
              <span className="block text-sm">{measure.title}</span>
              <span className="block text-xs text-muted-foreground">{measure.detail}</span>
              {measure.audience === "public" && (
                <span className="mt-1 inline-block rounded-sm border border-border px-1.5 text-[11px] text-muted-foreground">
                  Draft, not sent
                </span>
              )}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** What to do now, by audience. Public notices are drafts; nothing goes out from here. */
export default function ReactiveMeasures({ measures }: { measures: ReactiveMeasure[] }) {
  return (
    <section aria-labelledby="reactive-measures-title" className="mt-4 border-t border-border pt-3">
      <h3 id="reactive-measures-title" className="text-sm font-medium">Reactive Measures</h3>
      <div className="mt-2 space-y-3">
        <Group title="Rangers" measures={measures.filter((m) => m.audience === "rangers")} />
        <Group
          title="Public notice"
          note="Drafts, not sent"
          measures={measures.filter((m) => m.audience === "public")}
        />
      </div>
    </section>
  );
}
