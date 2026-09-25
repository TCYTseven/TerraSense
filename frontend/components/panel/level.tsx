import { riskLabel } from "@/lib/format";
import type { RiskLevel } from "@/lib/types";

// Literal class names so Tailwind generates each one. Risk colors mark risk only.
export const LEVEL_TEXT: Record<RiskLevel, string> = {
  low: "text-risk-low",
  moderate: "text-risk-moderate",
  high: "text-risk-high",
  extreme: "text-risk-extreme",
};

const LEVEL_DOT: Record<RiskLevel, string> = {
  low: "bg-risk-low",
  moderate: "bg-risk-moderate",
  high: "bg-risk-high",
  extreme: "bg-risk-extreme",
};

/** The High and Extreme treatment: a 3 px left border in the level color and an 8% tint. */
export const LEVEL_TREATMENT: Record<RiskLevel, string> = {
  low: "",
  moderate: "",
  high: "border-l-3 border-risk-high bg-risk-high/8",
  extreme: "border-l-3 border-risk-extreme bg-risk-extreme/8",
};

/** A level dot and its word, in the level color. The color never carries the level alone. */
export function LevelWord({ level, className = "" }: { level: RiskLevel; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 ${LEVEL_TEXT[level]} ${className}`}>
      <span aria-hidden className={`size-[0.55em] shrink-0 rounded-full ${LEVEL_DOT[level]}`} />
      {riskLabel(level)}
    </span>
  );
}

/** Shown beside the level word when the agents disagree by two or more levels. */
export function NeedsReviewTag() {
  return (
    <span className="rounded-sm border border-border px-1.5 py-0.5 text-xs font-normal text-muted-foreground">
      Needs review
    </span>
  );
}
