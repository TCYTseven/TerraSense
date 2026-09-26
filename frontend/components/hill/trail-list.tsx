import { LEVEL_TEXT } from "@/components/panel/level";
import { formatScore, riskLabel } from "@/lib/format";
import type { TrailLetter, TrailRisk } from "@/lib/hill";
import TrailBadge from "./trail-badge";

export interface TrailListProps {
  /** The top five, riskiest first. */
  trails: TrailRisk[];
  /** The row last viewed, or null. */
  selected: TrailLetter | null;
  onView: (letter: TrailLetter) => void;
}

// Literal class names so Tailwind generates each one.
const DOT: Record<TrailRisk["level"], string> = {
  low: "bg-risk-low",
  moderate: "bg-risk-moderate",
  high: "bg-risk-high",
  extreme: "bg-risk-extreme",
};

/** The five most at-risk trails. "View" flies the map to the trail's marker. */
export default function TrailList({ trails, selected, onView }: TrailListProps) {
  return (
    <section aria-labelledby="trails-heading" className="border-t border-border py-4">
      <h2 id="trails-heading" className="px-5 text-sm text-muted-foreground">
        Top {trails.length} at-risk trails
      </h2>
      <ol className="mt-2">
        {trails.map((trail) => {
          const isSelected = trail.letter === selected;
          return (
            <li
              key={trail.id}
              aria-current={isSelected ? "true" : undefined}
              className={`flex items-center gap-3 border-l-2 py-2.5 pl-[18px] pr-5 text-base ${
                isSelected ? "border-primary bg-accent" : "border-transparent"
              }`}
            >
              <TrailBadge letter={trail.letter} level={trail.level} />
              <span className="min-w-0 flex-1">
                <span className="block truncate">{trail.name}</span>
                {(trail.primaryFactor !== null || trail.slopeDeg !== null) && (
                  <span className="block text-sm text-muted-foreground">
                    {trail.primaryFactor}
                    {trail.primaryFactor !== null && trail.slopeDeg !== null && " · "}
                    {trail.slopeDeg !== null && <span className="font-mono">{trail.slopeDeg}°</span>}
                  </span>
                )}
              </span>
              <span className={`flex shrink-0 items-center gap-1.5 ${LEVEL_TEXT[trail.level]}`}>
                <span aria-hidden className={`size-[0.55em] rounded-full ${DOT[trail.level]}`} />
                <span className="font-mono text-[0.92em]">{formatScore(trail.score)}</span>
                <span className="sr-only">{riskLabel(trail.level)}</span>
              </span>
              <button
                type="button"
                onClick={() => onView(trail.letter)}
                aria-label={`View ${trail.name} on the map`}
                className="h-8 shrink-0 rounded-md border border-primary px-3 text-sm font-medium text-primary hover:bg-primary/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
              >
                View
              </button>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
