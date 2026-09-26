import type { TrailLetter } from "@/lib/hill";
import type { RiskLevel } from "@/lib/types";

// Literal class names so Tailwind generates each one. Risk colors mark risk only.
const BADGE_FILL: Record<RiskLevel, string> = {
  low: "bg-risk-low",
  moderate: "bg-risk-moderate",
  high: "bg-risk-high",
  extreme: "bg-risk-extreme",
};

/**
 * A trail's letter in a small circle of its level color, dark text. The map marker for the same
 * trail uses the same circle, so a row and its marker read as one thing.
 */
export default function TrailBadge({ letter, level }: { letter: TrailLetter; level: RiskLevel }) {
  return (
    <span
      aria-hidden
      className={`inline-flex size-6 shrink-0 items-center justify-center rounded-full font-mono text-xs font-semibold leading-none text-background ${BADGE_FILL[level]}`}
    >
      {letter}
    </span>
  );
}
