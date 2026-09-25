import { XIcon } from "@/components/icons";
import { formatScore, hazardLabel } from "@/lib/format";
import type { Hazard } from "@/lib/types";
import { LEVEL_TREATMENT, LevelWord, NeedsReviewTag } from "./level";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 text-sm">{children}</dd>
    </div>
  );
}

/**
 * The hazard, in four lines and always in this order: what it is, why it was flagged,
 * confidence, and how to avoid it. It opens with the pin and closes with it.
 */
export default function HazardBlock({ hazard, onClose }: { hazard: Hazard; onClose: () => void }) {
  const preview = hazard.run_id === null;
  return (
    <section
      aria-labelledby="hazard-heading"
      className={`border-t border-border px-5 py-4 ${LEVEL_TREATMENT[hazard.severity]}`}
    >
      <div className="flex items-center justify-between gap-3">
        <h2 id="hazard-heading" className="flex flex-wrap items-center gap-2 text-sm font-medium">
          {hazardLabel(hazard.type)}
          <LevelWord level={hazard.severity} className="font-medium" />
          {hazard.needs_review && <NeedsReviewTag />}
        </h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close the hazard details"
          className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          <XIcon className="size-4" />
        </button>
      </div>
      <dl className="mt-3 space-y-3">
        <Field label="What it is">{hazard.what ?? "No description yet."}</Field>
        <Field label="Why it was flagged">{hazard.why ?? "No explanation yet."}</Field>
        <Field label="Confidence">
          {hazard.confidence !== null ? (
            <span className="font-mono text-[0.92em]">{formatScore(hazard.confidence)}</span>
          ) : (
            <span className="text-muted-foreground">Not scored: a preview from the heat map, before the agents ran.</span>
          )}
        </Field>
        <Field label="How to avoid it">{hazard.how_to_avoid ?? "No advice yet."}</Field>
      </dl>
      {preview && <p className="mt-3 text-xs text-muted-foreground">Analyze now replaces this preview with the agents&apos; assessment.</p>}
    </section>
  );
}
